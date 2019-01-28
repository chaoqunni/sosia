from collections import defaultdict
from functools import partial
from operator import attrgetter
from string import Template

from scopus import AbstractRetrieval, AuthorSearch, ScopusSearch

from scopus.exception import Scopus400Error, ScopusQueryError,\
    Scopus500Error, Scopus404Error
from sosia.utils import clean_abstract, print_progress, run


def find_country(auth_ids, pubs, year):
    """Find the most common country of affiliations of a scientist using her
    most recent publications listing valid affiliations.

    Parameters
    ----------
    auth_ids : list of str
        A list of Scopus Author Profile IDs for which the affiliation should
        be searched for.

    pubs : list of namedtuple
        The publications associated with the Author IDs as returned from a
        scopus query.

    year : int
        The year for which we would like to have the country.

    Returns
    -------
    country : str or None
        The country of the scientist in the year closest to the given year,
        given that the publications list valid affiliations.  Equals None when
        no valid publications are found.
    """
    # Available papers of most recent year with publications
    papers = [p for p in pubs if int(p.coverDate[:4]) <= year]
    papers = sorted(papers, key=attrgetter('coverDate'), reverse=True)
    for p in papers:
        authorgroup = AbstractRetrieval(p.eid).authorgroup
        if not authorgroup:
            continue
        countries = [a.country for a in authorgroup if
                     a.auid in auth_ids and a.country]
        if not countries:
            continue
        return ";".join(countries)


def get_authors(pubs):
    """Get list of author IDs from a list of namedtuples representing
    publications.
    """
    l = [x.author_ids.split(';') for x in pubs if isinstance(x.author_ids, str)]
    return [au for sl in l for au in sl]


def parse_doc(eids, refresh):
    """Find abstract and references of articles published up until
    the given year, both as continuous string.

    Parameters
    ----------
    eids : list of str
        Scopus Document EIDs representing documents to be considered.

    refresh : bool
        Whether to refresh the cached files if they exist, or not.

    Returns
    -------
    d : dict
        A dictionary with two keys: "refs" and "abstracts".  d['refs']
        includes the continuous string of Scopus Abstract EIDs representing
        cited references, joined on a blank.  d['abstracts'] includes
        the continuous string of cleaned abstracts, joined on a blank.
    """
    docs = []
    for eid in eids:
        try:
            docs.append(AbstractRetrieval(eid, view='FULL', refresh=refresh))
        except Scopus404Error:
            docs.append(None)
    # Filter None's
    absts = [clean_abstract(ab.abstract) for ab in docs if ab.abstract]
    refs = [ab.references for ab in docs if ab.references]
    return {'refs': " ".join([ref.id for sl in refs for ref in sl]),
            'abstracts': " ".join(absts), 'miss_abs': len(eids) - len(absts),
            'miss_refs': len(eids) - len(refs)}


def query(q_type, q, refresh=False, first_try=True):
    """Wrapper function to perform a particular search query

    Parameters
    ----------
    q_type : str
        Determines the query search that will be used.  Allowed values:
        "author", "docs".

    q : str
        The query string.

    refresh : bool (optional, default=False)
        Whether to refresh cached files if they exist, or not.

    first_try: bool (optional, default=True)
        A flag parameter to indicate whether the function has been called
        for the first time.  If False, KeyErrors will result in abortion.

    Returns
    -------
    res : list of namedtuples
        Documents represented by namedtuples as returned from scopus.

    Raises
    ------
    ValueError:
        If q_type is none of the allowed values.
    """
    try:
        if q_type == "author":
            res = AuthorSearch(q, refresh=refresh).authors
        elif q_type == "docs":
            res = ScopusSearch(q, refresh=refresh).results
            for pub in res:   # Verify that `year` is integer
                int(pub.coverDate[:4])
        else:
            raise Exception("Unknown value provided.")
        return res
    except (KeyError, UnicodeDecodeError, ValueError):
        if first_try:
            return query(q_type, q, True, False)
        else:
            pass


def query_journal(source_id, years, refresh):
    """Get authors by year for a particular source.

    Parameters
    ----------
    source_id : str or int
        The Scopus ID of the source.

    years : container of int or container of str
        The relevant pulication years to search for.

    refresh : bool (optional)
        Whether to refresh cached files if they exist, or not.

    Returns
    -------
    d : dict
        Dictionary keyed by year listing all authors who published in
        that year.
    """
    try:  # Try complete publication list first
        res = query("docs", 'SOURCE-ID({})'.format(source_id), refresh=refresh)
    except (ScopusQueryError, Scopus500Error):  # Fall back to year-wise queries
        res = []
        for year in years:
            q = Template('SOURCE-ID({}) AND PUBYEAR IS $fill'.format(source_id))
            ext, _ = stacked_query([year], res, q, "", partial(query, "docs"),
                                   refresh=refresh)
            res.extend(ext)
    # Sort authors by year
    d = defaultdict(list)
    for pub in res:
        year = pub.coverDate[:4]
        d[year].extend(get_authors([pub]))  # Populate dict
    return d


def stacked_query(group, res, query, joiner, func, refresh, i=0, total=None):
    """Auxiliary function to recursively perform queries until they work.

    Parameters
    ----------
    group : list of str
        Scopus IDs (of authors or sources) for which the stacked query should
        be conducted.

    res : list
        (Initially empty )Container to which the query results will be
        appended.

    query : Template()
        A string template with one paramter named `fill` which will be used
        as search query.

    joiner : str
        On wich the group elements should be joined to fill the query.

    func : function object
        The function to be used (ScopusSearch, AuthorSearch).  Should be
        provided with partial and additional parameters.

    refresh : bool
        Whether the cached files should be refreshed or not.

    i : int (optional, default=0)
        A count variable to be used for printing the progress bar.

    total : int (optional, default=None)
        The total number of elements in the group.  If provided, a progress
        bar will be printed.

    Returns
    -------
    res : list
        A list of namedtuples representing publications.

    i : int
        A running variable to indicate the progress.

    Notes
    -----
    Results of each successful query are appended to ´res´.
    """
    group = [str(g) for g in group]  # make robust to passing int
    q = query.substitute(fill=joiner.join(group))
    try:
        res.extend(run(func, q, refresh))
        if total:  # Equivalent of verbose
            i += len(group)
            print_progress(i, total)
    except (Scopus400Error, ScopusQueryError, Scopus500Error):
        if len(group) > 1:
            mid = len(group) // 2
            params = {"group": group[:mid], "res": res, "query": query, "i": i,
                      "joiner": joiner, "func": func, "total": total,
                      "refresh": refresh}
            res, i = stacked_query(**params)
            params.update({"group": group[mid:], "i": i})
            res, i = stacked_query(**params)
        elif "AND EID(" not in q:  # skip if already passed inside here
            groupeids = ["*" + str(n) for n in range(0, 10)]
            q = Template(q + " AND EID($fill)")
            mid = len(groupeids) // 2  # split here to avoid redundant query
            params = {"group": groupeids[:mid], "res": res, "query": q, "i": i,
                      "joiner": " OR ", "func": func, "total": None,
                      "refresh": refresh}
            res, i = stacked_query(**params)
            params.update({"group": groupeids[mid:], "i": i})
            res, i = stacked_query(**params)
        else:
            return None, i
    return res, i