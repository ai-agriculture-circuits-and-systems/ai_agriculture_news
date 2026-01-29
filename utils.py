import datetime
import json
import logging
import os
import re
import shutil
import time
from typing import Dict, List

import pytz
import urllib
import urllib.error
import urllib.request
import urllib3
import requests

import feedparser
from easydict import EasyDict

# Set up logger
logger = logging.getLogger(__name__)


def remove_duplicated_spaces(text: str) -> str:
    """Collapse duplicate whitespace characters into single spaces.

    Args:
        text: Input text that may contain duplicated whitespace.

    Returns:
        A string with all consecutive whitespace collapsed into a single space.
    """
    return " ".join(text.split())


def request_paper_with_arxiv_api(
    keyword: str,
    max_results: int,
    link: str = "OR",
) -> List[Dict[str, str]]:
    """Request papers from the arXiv API for a given keyword.

    Args:
        keyword: Search keyword that will be used in both title and abstract.
        max_results: Maximum number of results to retrieve from arXiv.
        link: Logical operator between title and abstract conditions, either
            ``"OR"`` or ``"AND"``.

    Returns:
        A list of dictionaries describing papers, each containing the default
        columns: ``Title``, ``Authors``, ``Abstract``, ``Link``, ``Tags``,
        ``Comment`` and ``Date``.

    Raises:
        AssertionError: If ``link`` is not ``"OR"`` or ``"AND"``.
        Exception: If there is any error when calling the arXiv API.
    """
    assert link in ["OR", "AND"], "link should be 'OR' or 'AND'"
    keyword = "\"" + keyword + "\""
    url = (
        "http://export.arxiv.org/api/query?"
        "search_query=ti:{0}+{2}+abs:{0}&max_results={1}&sortBy=lastUpdatedDate"
    ).format(keyword, max_results, link)
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")

    logger.info("Requesting papers from arXiv API for keyword: %s", keyword)
    try:
        response = urllib.request.urlopen(url).read().decode("utf-8")
        feed = feedparser.parse(response)
        logger.info("Successfully retrieved %d papers from arXiv API", len(feed.entries))
    except Exception as exc:
        logger.error("Failed to fetch papers from arXiv API: %s", exc)
        raise

    # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Date
    papers: List[Dict[str, str]] = []
    for entry in feed.entries:
        try:
            entry_ez = EasyDict(entry)
            paper: Dict[str, str] = {}

            # title
            paper["Title"] = remove_duplicated_spaces(
                entry_ez.title.replace("\n", " "),
            )
            # abstract
            paper["Abstract"] = remove_duplicated_spaces(
                entry_ez.summary.replace("\n", " "),
            )
            # authors
            paper["Authors"] = [
                remove_duplicated_spaces(author["name"].replace("\n", " "))
                for author in entry_ez.authors
            ]
            # link
            paper["Link"] = remove_duplicated_spaces(
                entry_ez.link.replace("\n", " "),
            )
            # tags
            paper["Tags"] = [
                remove_duplicated_spaces(tag["term"].replace("\n", " "))
                for tag in entry_ez.tags
            ]
            # comment
            paper["Comment"] = remove_duplicated_spaces(
                entry_ez.get("arxiv_comment", "").replace("\n", " "),
            )
            # date
            paper["Date"] = entry_ez.updated

            papers.append(paper)
        except Exception as exc:
            logger.warning("Failed to process paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d papers", len(papers))
    return papers


def request_papers_with_crossref(
    keyword: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Request papers using the CrossRef API (metadata only).

    Args:
        keyword: Search keyword to query in CrossRef.
        max_results: Maximum number of results to retrieve.

    Returns:
        A list of paper dictionaries normalised to the common schema.
    """
    params = {
        "query": keyword,
        "rows": max_results,
        "sort": "published",
        "order": "desc",
    }
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)

    logger.info("Requesting papers from CrossRef for keyword: %s", keyword)
    try:
        request = urllib.request.Request(
            url,
            headers={
                # CrossRef requires a descriptive User-Agent including contact info.
                "User-Agent": (
                    "ai-agriculture-news-bot/0.1 "
                    "(mailto:YOUR_EMAIL@example.com)"
                ),
            },
        )
        with urllib.request.urlopen(request) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        items = data.get("message", {}).get("items", [])
        logger.info("Successfully retrieved %d papers from CrossRef", len(items))
    except Exception as exc:
        logger.error("Failed to fetch papers from CrossRef: %s", exc)
        raise

    papers: List[Dict[str, str]] = []
    for item in items:
        try:
            title_list = item.get("title") or []
            title = title_list[0] if title_list else "Untitled"

            abstract_raw = item.get("abstract", "") or ""
            abstract_text = re.sub(r"<.*?>", "", abstract_raw)

            authors_raw = item.get("author") or []
            authors = []
            for author in authors_raw:
                given = author.get("given", "")
                family = author.get("family", "")
                name = (given + " " + family).strip()
                if name:
                    authors.append(name)

            url_item = item.get("URL", "")

            date_parts = (
                item.get("issued", {}).get("date-parts")
                or item.get("published-print", {}).get("date-parts")
                or item.get("published-online", {}).get("date-parts")
                or []
            )
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
                month = date_parts[0][1] if len(date_parts[0]) > 1 else 1
                day = date_parts[0][2] if len(date_parts[0]) > 2 else 1
                date_str = f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"
            else:
                date_str = "1970-01-01T00:00:00Z"

            container_list = item.get("container-title") or []
            container = container_list[0] if container_list else ""

            paper: Dict[str, str] = {
                "Title": remove_duplicated_spaces(title.replace("\n", " ")),
                "Abstract": remove_duplicated_spaces(abstract_text.replace("\n", " ")),
                "Authors": authors or ["Unknown"],
                "Link": url_item,
                "Tags": ["CrossRef"],
                "Comment": container,
                "Date": date_str,
            }
            papers.append(paper)
        except Exception as exc:
            logger.warning("Failed to process CrossRef paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d CrossRef papers", len(papers))
    return papers


def request_papers_with_openalex(
    keyword: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Request papers using the OpenAlex API (metadata only).

    Args:
        keyword: Search keyword to query in OpenAlex.
        max_results: Maximum number of results to retrieve.

    Returns:
        A list of paper dictionaries normalised to the common schema.
    """
    params = {
        "search": keyword,
        "per-page": max_results,
        "sort": "publication_date:desc",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)

    logger.info("Requesting papers from OpenAlex for keyword: %s", keyword)
    try:
        with urllib.request.urlopen(url) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        results = data.get("results", [])
        logger.info("Successfully retrieved %d papers from OpenAlex", len(results))
    except Exception as exc:
        logger.error("Failed to fetch papers from OpenAlex: %s", exc)
        raise

    papers: List[Dict[str, str]] = []
    for item in results:
        try:
            title = item.get("title") or "Untitled"
            abstract_inverted = item.get("abstract_inverted_index") or {}
            # Flatten inverted index to a text snippet if available.
            if abstract_inverted:
                # abstract_inverted is {word: [positions...]}; reconstruct a rough abstract.
                positions: Dict[int, str] = {}
                for word, idxs in abstract_inverted.items():
                    for idx in idxs:
                        positions[idx] = word
                abstract_words = [positions[i] for i in sorted(positions.keys())]
                abstract_text = " ".join(abstract_words)
            else:
                abstract_text = ""

            authorships = item.get("authorships") or []
            authors = []
            for auth in authorships:
                author_info = auth.get("author", {})
                name = author_info.get("display_name", "")
                if name:
                    authors.append(name)

            url_item = item.get("primary_location", {}).get("landing_page_url") or item.get(
                "id",
                "",
            )

            date_str = item.get("publication_date") or "1970-01-01"
            if "T" not in date_str:
                date_str = f"{date_str}T00:00:00Z"

            venue = ""
            if item.get("host_venue"):
                venue = item["host_venue"].get("display_name", "") or ""

            paper = {
                "Title": remove_duplicated_spaces(title.replace("\n", " ")),
                "Abstract": remove_duplicated_spaces(abstract_text.replace("\n", " ")),
                "Authors": authors or ["Unknown"],
                "Link": url_item,
                "Tags": ["OpenAlex"],
                "Comment": venue,
                "Date": date_str,
            }
            papers.append(paper)
        except Exception as exc:
            logger.warning("Failed to process OpenAlex paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d OpenAlex papers", len(papers))
    return papers


def request_papers_with_semantic_scholar(
    keyword: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Request papers using the Semantic Scholar API (metadata only).

    Args:
        keyword: Search keyword to query in Semantic Scholar.
        max_results: Maximum number of results to retrieve.

    Returns:
        A list of paper dictionaries normalised to the common schema.
    """
    params = {
        "query": keyword,
        "limit": max_results,
        "offset": 0,
        "fields": "title,abstract,authors,venue,year,url",
    }
    url = (
        "https://api.semanticscholar.org/graph/v1/paper/search?"
        + urllib.parse.urlencode(params)
    )

    logger.info("Requesting papers from Semantic Scholar for keyword: %s", keyword)
    try:
        with urllib.request.urlopen(url) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        items = data.get("data", [])
        logger.info(
            "Successfully retrieved %d papers from Semantic Scholar",
            len(items),
        )
    except Exception as exc:
        logger.error("Failed to fetch papers from Semantic Scholar: %s", exc)
        raise

    papers: List[Dict[str, str]] = []
    for item in items:
        try:
            title = item.get("title") or "Untitled"
            abstract_text = item.get("abstract") or ""

            authors_raw = item.get("authors") or []
            authors = []
            for author in authors_raw:
                name = author.get("name", "")
                if name:
                    authors.append(name)

            url_item = item.get("url", "")

            year = item.get("year")
            if year:
                date_str = f"{int(year):04d}-01-01T00:00:00Z"
            else:
                date_str = "1970-01-01T00:00:00Z"

            venue = item.get("venue", "") or ""

            paper = {
                "Title": remove_duplicated_spaces(title.replace("\n", " ")),
                "Abstract": remove_duplicated_spaces(abstract_text.replace("\n", " ")),
                "Authors": authors or ["Unknown"],
                "Link": url_item,
                "Tags": ["SemanticScholar"],
                "Comment": venue,
                "Date": date_str,
            }
            papers.append(paper)
        except Exception as exc:
            logger.warning("Failed to process Semantic Scholar paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d Semantic Scholar papers", len(papers))
    return papers


def request_papers_with_acm_api(
    keyword: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Request papers from the ACM Digital Library API using a keyword.

    This function assumes you have configured an ACM API access token in the
    ``ACM_ACCESS_TOKEN`` environment variable. The exact endpoint and query
    parameters may need to be adjusted to match your ACM subscription or API
    documentation. The default implementation targets the generic metadata
    endpoint suggested by dltHub's ACM Digital Library connector
    (`acm_digital_library_migrations`) [1]_.

    Args:
        keyword: Free-text keyword query to search ACM metadata.
        max_results: Maximum number of records to return.

    Returns:
        A list of paper dictionaries normalised to the common schema.

    Raises:
        RuntimeError: If the ACM access token is not configured.

    References:
        .. [1] dltHub ACM Digital Library connector documentation.
    """
    access_token = os.getenv("ACM_ACCESS_TOKEN")
    if not access_token:
        raise RuntimeError(
            "ACM_ACCESS_TOKEN environment variable is not set. "
            "Please configure your ACM API access token before using the ACM "
            "metadata integration.",
        )

    base_url = os.getenv("ACM_BASE_URL", "https://dl.acm.org/v/")
    # The exact path and parameters depend on your ACM API contract. Here we
    # follow the pattern from dltHub's example, hitting a generic metadata
    # endpoint and passing a simple query string and pagination.
    metadata_url = urllib.parse.urljoin(base_url, "api/metadata")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    page = 0
    page_size = min(max_results, 100)
    collected: List[Dict[str, str]] = []

    while len(collected) < max_results:
        params = {
            "q": keyword,
            "page": page,
            "size": page_size,
        }
        logger.info(
            "Requesting ACM metadata page=%d size=%d keyword=%s",
            page,
            page_size,
            keyword,
        )
        try:
            response = requests.get(
                metadata_url,
                params=params,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Failed to fetch ACM metadata: %s", exc)
            break

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            logger.error("Failed to decode ACM metadata JSON: %s", exc)
            break

        # The exact structure depends on the ACM API. We assume a top-level
        # "items" list for now; adjust if your API uses a different field.
        items = payload.get("items") or payload.get("data") or []
        if not items:
            logger.info("ACM metadata query returned no more items.")
            break

        for item in items:
            collected.append(item)
            if len(collected) >= max_results:
                break

        page += 1

    papers: List[Dict[str, str]] = []
    for item in collected:
        try:
            title = (
                item.get("title")
                or item.get("articleTitle")
                or item.get("fullTitle")
                or "Untitled"
            )
            abstract_text = item.get("abstract") or ""

            authors_raw = item.get("authors") or item.get("creators") or []
            authors: List[str] = []
            for author in authors_raw:
                name = (
                    author.get("name")
                    or author.get("preferredName")
                    or author.get("fullName")
                )
                if not name:
                    first = author.get("firstName", "")
                    last = author.get("lastName", "")
                    name = (first + " " + last).strip()
                if name:
                    authors.append(name)

            doi = item.get("doi")
            url_item = item.get("url") or ""
            if not url_item and doi:
                url_item = f"https://doi.org/{doi}"

            pub_date = (
                item.get("publicationDate")
                or item.get("date")
                or item.get("published")
            )
            year = item.get("year")

            if pub_date and isinstance(pub_date, str):
                if "T" in pub_date:
                    date_str = pub_date
                elif re.match(r"\d{4}-\d{2}-\d{2}", pub_date):
                    date_str = f"{pub_date}T00:00:00Z"
                else:
                    if year:
                        date_str = f"{int(year):04d}-01-01T00:00:00Z"
                    else:
                        date_str = "1970-01-01T00:00:00Z"
            elif year:
                date_str = f"{int(year):04d}-01-01T00:00:00Z"
            else:
                date_str = "1970-01-01T00:00:00Z"

            venue = (
                item.get("publicationTitle")
                or item.get("journal")
                or item.get("conference")
                or ""
            )

            paper: Dict[str, str] = {
                "Title": remove_duplicated_spaces(title.replace("\n", " ")),
                "Abstract": remove_duplicated_spaces(abstract_text.replace("\n", " ")),
                "Authors": authors or ["Unknown"],
                "Link": url_item,
                "Tags": ["ACM"],
                "Comment": venue,
                "Date": date_str,
            }
            papers.append(paper)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to process ACM paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d ACM papers", len(papers))
    return papers


def _ieee_search_page(
    query_text: str,
    page: int,
    rows_per_page: int = 100,
    get_page_number: bool = False,
    retry: int = 5,
) -> Dict[str, str] | List[Dict[str, str]] | None:
    """Call the IEEE Xplore internal search endpoint for a single page.

    This is adapted from the CIRDC conference download script, but refactored
    to support arbitrary keyword queries and to return results instead of
    writing JSON files.

    Args:
        query_text: The IEEE Xplore ``queryText`` expression.
        page: 1-based page index to request.
        rows_per_page: Number of records per page (IEEE typically allows 100).
        get_page_number: If True, return only the total number of pages.
        retry: Maximum number of retries on request/parse failures.

    Returns:
        If ``get_page_number`` is True, returns the integer number of pages.
        Otherwise returns the list of ``records`` for the page, or ``None`` on
        persistent failure.
    """
    logger.info(
        "IEEE search page query=%s page=%d get_page_number=%s",
        query_text,
        page,
        get_page_number,
    )
    if get_page_number:
        assert page == 1

    data = {
        "newsearch": "true",
        "highlight": "true",
        "matchBoolean": "true",
        "matchPubs": "true",
        "action": "search",
        "queryText": query_text,
        "pageNumber": str(page),
        "rowsPerPage": rows_per_page,
    }

    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "gzip,deflate,br",
        "Accept-Language": "en-US,en;q=0.8",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Referer": "https://ieeexplore.ieee.org/search/searchresult.jsp?newsearch=true",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/108.0.0.0 Safari/537.36"
        ),
    }

    url = "https://ieeexplore.ieee.org/rest/search"
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    for attempt in range(retry):
        try:
            response = requests.post(
                url=url,
                data=json.dumps(data),
                headers=headers,
                timeout=30,
                verify=False,
            )
            response.raise_for_status()

            try:
                payload = response.json()
            except json.JSONDecodeError:
                logger.warning(
                    "IEEE JSON decode error on page %d, attempt %d of %d",
                    page,
                    attempt + 1,
                    retry,
                )
                continue

            if get_page_number:
                total_pages = int(payload.get("totalPages", 0))
                logger.info("IEEE keyword search totalPages=%d", total_pages)
                return total_pages

            records = payload.get("records", [])
            if not isinstance(records, list):
                logger.error("IEEE response missing 'records' on page %d", page)
                return None

            logger.info("IEEE page %d returned %d records", page, len(records))
            return records
        except requests.RequestException as exc:
            logger.warning(
                "IEEE request error on page %d, attempt %d of %d: %s",
                page,
                attempt + 1,
                retry,
                exc,
            )

    logger.error("Failed IEEE search page after %d attempts (page=%d)", retry, page)
    return None


def request_papers_with_ieee_keyword(
    keyword: str,
    max_results: int,
) -> List[Dict[str, str]]:
    """Request papers from IEEE Xplore using a keyword-based search.

    This function uses the same internal ``/rest/search`` endpoint and request
    structure as CIRDC, but issues a keyword query instead of a publication
    number filter and returns records directly in memory.

    Args:
        keyword: Free-text keyword query (matched against IEEE metadata).
        max_results: Maximum number of records to return across all pages.

    Returns:
        A list of paper dictionaries normalised to the common schema.
    """
    # Simple all-metadata keyword query; this mirrors the behaviour of the
    # IEEE Xplore search UI. More complex queries can be plugged in later.
    query_text = keyword

    logger.info("Requesting IEEE papers for keyword: %s", keyword)

    all_records: List[Dict[str, str]] = []

    total_pages_obj = _ieee_search_page(
        query_text=query_text,
        page=1,
        get_page_number=True,
    )
    if not isinstance(total_pages_obj, int) or total_pages_obj <= 0:
        logger.warning("IEEE keyword search returned no pages for '%s'", keyword)
        return []

    total_pages = total_pages_obj

    for page in range(1, total_pages + 1):
        if len(all_records) >= max_results:
            break
        records = _ieee_search_page(
            query_text=query_text,
            page=page,
            get_page_number=False,
        )
        if not records:
            continue
        for record in records:
            all_records.append(record)
            if len(all_records) >= max_results:
                break

    papers: List[Dict[str, str]] = []
    for rec in all_records:
        try:
            title = rec.get("articleTitle") or rec.get("title") or "Untitled"
            abstract_text = rec.get("abstract") or ""

            authors_raw = rec.get("authors") or []
            authors: List[str] = []
            for author in authors_raw:
                name = (
                    author.get("preferredName")
                    or author.get("fullName")
                    or author.get("firstName", "") + " " + author.get("lastName", "")
                ).strip()
                if name:
                    authors.append(name)

            article_number = rec.get("articleNumber")
            doi = rec.get("doi")
            if article_number:
                link = f"https://ieeexplore.ieee.org/document/{article_number}"
            elif doi:
                link = f"https://doi.org/{doi}"
            else:
                link = ""

            pub_date = rec.get("publicationDate") or ""
            pub_year = rec.get("publicationYear")

            if pub_date:
                # IEEE dates are often like "2023-05-01" or "01 May 2023".
                if "T" in pub_date:
                    date_str = pub_date
                elif re.match(r"\d{4}-\d{2}-\d{2}", pub_date):
                    date_str = f"{pub_date}T00:00:00Z"
                else:
                    # Fallback: just use year if available.
                    if pub_year:
                        date_str = f"{int(pub_year):04d}-01-01T00:00:00Z"
                    else:
                        date_str = "1970-01-01T00:00:00Z"
            elif pub_year:
                date_str = f"{int(pub_year):04d}-01-01T00:00:00Z"
            else:
                date_str = "1970-01-01T00:00:00Z"

            venue = rec.get("publicationTitle") or ""

            paper: Dict[str, str] = {
                "Title": remove_duplicated_spaces(title.replace("\n", " ")),
                "Abstract": remove_duplicated_spaces(abstract_text.replace("\n", " ")),
                "Authors": authors or ["Unknown"],
                "Link": link,
                "Tags": ["IEEE"],
                "Comment": venue,
                "Date": date_str,
            }
            papers.append(paper)
        except Exception as exc:
            logger.warning("Failed to process IEEE paper entry: %s", exc)
            continue

    logger.info("Successfully processed %d IEEE papers", len(papers))
    return papers

def filter_tags(
    papers: List[Dict[str, str]],
    target_fileds: List[str] = ["cs", "stat"],
) -> List[Dict[str, str]]:
    logger.info("Filtering papers by tags: %s", target_fileds)
    # filtering tags: only keep the papers in target_fileds
    results = []
    for paper in papers:
        tags = paper.get("Tags", [])
        for tag in tags:
            if tag.split(".")[0] in target_fileds:
                results.append(paper)
                break
    logger.info(f"Filtered papers: {len(results)} out of {len(papers)} papers kept")
    return results


def get_daily_papers_by_keyword_with_retries(
    keyword: str,
    column_names: List[str],
    max_result: int,
    link: str = "OR",
    retries: int = 6,
) -> List[Dict[str, str]]:
    logger.info(
        "Attempting to get papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword(keyword, column_names, max_result, link)
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            else:
                logger.warning(
                    "Received empty list on attempt %d, retrying in 30 minutes...",
                    attempt + 1,
                )
                time.sleep(60 * 30)  # wait for 30 minutes
        except Exception as exc:
            logger.error("Error on attempt %d: %s", attempt + 1, exc)
            if attempt < retries - 1:
                logger.info("Waiting 30 minutes before retry...")
                time.sleep(60 * 30)
    
    logger.error("Failed to get papers after all retry attempts")
    return None


def get_daily_papers_by_keyword(
    keyword: str,
    column_names: List[str],
    max_result: int,
    link: str = "OR",
) -> List[Dict[str, str]]:
    logger.info("Getting papers for keyword: %s", keyword)
    # get papers
    papers = request_paper_with_arxiv_api(keyword, max_result, link)
    # NOTE filtering tags: only keep the papers in cs field
    papers = filter_tags(papers)
    # select columns for display
    papers = [{column_name: paper[column_name] for column_name in column_names} for paper in papers]
    logger.info(
        "Retrieved %d papers after filtering and column selection",
        len(papers),
    )
    return papers


def get_daily_papers_by_keyword_from_crossref(
    keyword: str,
    column_names: List[str],
    max_result: int,
) -> List[Dict[str, str]]:
    """Get papers for a keyword using CrossRef.

    Args:
        keyword: Search keyword.
        column_names: Column names to keep in the result.
        max_result: Maximum number of results to retrieve.

    Returns:
        A list of dictionaries ready for table generation.
    """
    logger.info("Getting CrossRef papers for keyword: %s", keyword)
    papers = request_papers_with_crossref(keyword, max_result)
    # select columns for display, falling back to empty string if missing
    processed: List[Dict[str, str]] = []
    for paper in papers:
        processed.append({column_name: paper.get(column_name, "") for column_name in column_names})
    logger.info("Retrieved %d CrossRef papers after column selection", len(processed))
    return processed


def get_daily_papers_by_keyword_from_openalex(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Get papers for a keyword using OpenAlex.

    Args:
        keyword: Search keyword.
        column_names: Column names to keep in the result.
        max_result: Maximum number of results to retrieve.
        max_result: Maximum number of results to retrieve.

    Returns:
        A list of dictionaries ready for table generation.
    """
    logger.info("Getting OpenAlex papers for keyword: %s", keyword)
    papers = request_papers_with_openalex(keyword, max_result)
    processed: List[Dict[str, str]] = []
    for paper in papers:
        processed.append(
            {column_name: paper.get(column_name, "") for column_name in column_names},
        )
    logger.info("Retrieved %d OpenAlex papers after column selection", len(processed))
    return processed


def get_daily_papers_by_keyword_from_semantic_scholar(
    keyword: str,
    column_names: List[str],
    max_result: int,
) -> List[Dict[str, str]]:
    """Get papers for a keyword using Semantic Scholar.

    Args:
        keyword: Search keyword.
        column_names: Column names to keep in the result.
        max_result: Maximum number of results to retrieve.

    Returns:
        A list of dictionaries ready for table generation.
    """
    logger.info("Getting Semantic Scholar papers for keyword: %s", keyword)
    papers = request_papers_with_semantic_scholar(keyword, max_result)
    processed: List[Dict[str, str]] = []
    for paper in papers:
        processed.append(
            {column_name: paper.get(column_name, "") for column_name in column_names},
        )
    logger.info(
        "Retrieved %d Semantic Scholar papers after column selection",
        len(processed),
    )
    return processed


def get_daily_papers_by_keyword_from_acm(
    keyword: str,
    column_names: List[str],
    max_result: int,
) -> List[Dict[str, str]]:
    """Get papers for a keyword using the ACM Digital Library API.

    Args:
        keyword: Search keyword.
        column_names: Column names to keep in the result.
        max_result: Maximum number of results to retrieve.

    Returns:
        A list of dictionaries ready for table generation.
    """
    logger.info("Getting ACM papers for keyword: %s", keyword)
    papers = request_papers_with_acm_api(keyword, max_result)
    processed: List[Dict[str, str]] = []
    for paper in papers:
        processed.append(
            {column_name: paper.get(column_name, "") for column_name in column_names},
        )
    logger.info("Retrieved %d ACM papers after column selection", len(processed))
    return processed


def get_daily_papers_by_keyword_from_ieee(
    keyword: str,
    column_names: List[str],
    max_result: int,
) -> List[Dict[str, str]]:
    """Get papers for a keyword using the IEEE Xplore keyword search."""
    logger.info("Getting IEEE papers for keyword: %s", keyword)
    papers = request_papers_with_ieee_keyword(keyword, max_result)
    processed: List[Dict[str, str]] = []
    for paper in papers:
        processed.append(
            {column_name: paper.get(column_name, "") for column_name in column_names},
        )
    logger.info("Retrieved %d IEEE papers after column selection", len(processed))
    return processed


def get_daily_papers_by_keyword_with_retries_crossref(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Retry wrapper for fetching papers via CrossRef."""
    logger.info(
        "Attempting to get CrossRef papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword_from_crossref(
                keyword,
                column_names,
                max_result,
            )
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d CrossRef papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            logger.warning(
                "Received empty CrossRef list on attempt %d, retrying soon...",
                attempt + 1,
            )
            time.sleep(60)
        except Exception as exc:
            logger.error("Error on CrossRef attempt %d: %s", attempt + 1, exc)
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                logger.error(
                    "CrossRef returned HTTP %d for keyword '%s'; "
                    "skipping further CrossRef retries for this keyword.",
                    exc.code,
                    keyword,
                )
                return []
            if attempt < retries - 1:
                logger.info("Waiting 60 seconds before CrossRef retry...")
                time.sleep(60)

    logger.error("Failed to get CrossRef papers after all retry attempts")
    return None


def get_daily_papers_by_keyword_with_retries_openalex(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Retry wrapper for fetching papers via OpenAlex."""
    logger.info(
        "Attempting to get OpenAlex papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword_from_openalex(
                keyword,
                column_names,
                max_result,
            )
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d OpenAlex papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            logger.warning(
                "Received empty OpenAlex list on attempt %d, retrying soon...",
                attempt + 1,
            )
            time.sleep(60)
        except Exception as exc:
            logger.error("Error on OpenAlex attempt %d: %s", attempt + 1, exc)
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                logger.error(
                    "OpenAlex returned HTTP %d for keyword '%s'; "
                    "skipping further OpenAlex retries for this keyword.",
                    exc.code,
                    keyword,
                )
                return []
            if attempt < retries - 1:
                logger.info("Waiting 60 seconds before OpenAlex retry...")
                time.sleep(60)

    logger.error("Failed to get OpenAlex papers after all retry attempts")
    return None


def get_daily_papers_by_keyword_with_retries_semantic_scholar(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Retry wrapper for fetching papers via Semantic Scholar."""
    logger.info(
        "Attempting to get Semantic Scholar papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword_from_semantic_scholar(
                keyword,
                column_names,
                max_result,
            )
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d Semantic Scholar papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            logger.warning(
                "Received empty Semantic Scholar list on attempt %d, retrying soon...",
                attempt + 1,
            )
            time.sleep(60)
        except Exception as exc:
            logger.error("Error on Semantic Scholar attempt %d: %s", attempt + 1, exc)
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                logger.error(
                    "Semantic Scholar returned HTTP %d for keyword '%s'; "
                    "skipping further Semantic Scholar retries for this keyword.",
                    exc.code,
                    keyword,
                )
                return []
            if attempt < retries - 1:
                logger.info("Waiting 60 seconds before Semantic Scholar retry...")
                time.sleep(60)

    logger.error(
        "Failed to get Semantic Scholar papers after all retry attempts",
    )
    return None


def get_daily_papers_by_keyword_with_retries_acm(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Retry wrapper for fetching papers via the ACM Digital Library API."""
    logger.info(
        "Attempting to get ACM papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword_from_acm(
                keyword,
                column_names,
                max_result,
            )
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d ACM papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            logger.warning(
                "Received empty ACM list on attempt %d, retrying soon...",
                attempt + 1,
            )
            time.sleep(60)
        except Exception as exc:  # noqa: BLE001
            logger.error("Error on ACM attempt %d: %s", attempt + 1, exc)
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                logger.error(
                    "ACM API returned HTTP %d for keyword '%s'; "
                    "skipping further ACM retries for this keyword.",
                    exc.code,
                    keyword,
                )
                return []
            if attempt < retries - 1:
                logger.info("Waiting 60 seconds before ACM retry...")
                time.sleep(60)

    logger.error("Failed to get ACM papers after all retry attempts")
    return None


def get_daily_papers_by_keyword_with_retries_ieee(
    keyword: str,
    column_names: List[str],
    max_result: int,
    retries: int = 3,
) -> List[Dict[str, str]]:
    """Retry wrapper for fetching papers via IEEE Xplore keyword search."""
    logger.info(
        "Attempting to get IEEE papers for keyword '%s' with %d retries",
        keyword,
        retries,
    )
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword_from_ieee(
                keyword,
                column_names,
                max_result,
            )
            if len(papers) > 0:
                logger.info(
                    "Successfully retrieved %d IEEE papers on attempt %d",
                    len(papers),
                    attempt + 1,
                )
                return papers
            logger.warning(
                "Received empty IEEE list on attempt %d, retrying soon...",
                attempt + 1,
            )
            time.sleep(60)
        except Exception as exc:
            logger.error("Error on IEEE attempt %d: %s", attempt + 1, exc)
            if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                logger.error(
                    "IEEE returned HTTP %d for keyword '%s'; "
                    "skipping further IEEE retries for this keyword.",
                    exc.code,
                    keyword,
                )
                return []
            if attempt < retries - 1:
                logger.info("Waiting 60 seconds before IEEE retry...")
                time.sleep(60)

    logger.error("Failed to get IEEE papers after all retry attempts")
    return None


def generate_table(papers: List[Dict[str, str]], ignore_keys: List[str] = []) -> str:
    logger.info("Generating table for %d papers", len(papers))
    formatted_papers = []
    keys = papers[0].keys()
    for paper in papers:
        try:
            # process fixed columns
            formatted_paper = EasyDict()
            ## Title and Link
            formatted_paper.Title = "**" + "[{0}]({1})".format(paper["Title"], paper["Link"]) + "**"
            ## Process Date (format: 2021-08-01T00:00:00Z -> 2021-08-01)
            formatted_paper.Date = paper["Date"].split("T")[0]
            
            # process other columns
            for key in keys:
                if key in ["Title", "Link", "Date"] or key in ignore_keys:
                    continue
                elif key == "Abstract":
                    # add show/hide button for abstract
                    formatted_paper[key] = "<details><summary>Show</summary><p>{0}</p></details>".format(paper[key])
                elif key == "Authors":
                    # NOTE only use the first author
                    formatted_paper[key] = paper[key][0] + " et al."
                elif key == "Tags":
                    tags = ", ".join(paper[key])
                    if len(tags) > 10:
                        formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(tags[:5], tags)
                    else:
                        formatted_paper[key] = tags
                elif key == "Comment":
                    if paper[key] == "":
                        formatted_paper[key] = ""
                    elif len(paper[key]) > 20:
                        formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(paper[key][:5], paper[key])
                    else:
                        formatted_paper[key] = paper[key]
            formatted_papers.append(formatted_paper)
        except Exception as exc:
            logger.warning("Failed to format paper: %s", exc)
            continue

    # generate header
    columns = formatted_papers[0].keys()
    # highlight headers
    columns = ["**" + column + "**" for column in columns]
    header = "| " + " | ".join(columns) + " |"
    header = header + "\n" + "| " + " | ".join(["---"] * len(formatted_papers[0].keys())) + " |"
    # generate the body
    body = ""
    for paper in formatted_papers:
        body += "\n| " + " | ".join(paper.values()) + " |"
    
    logger.info("Successfully generated table")
    return header + body

def back_up_files():
    logger.info("Backing up files")
    try:
        # back up README.md and ISSUE_TEMPLATE.md
        shutil.move("README.md", "README.md.bk")
        shutil.move(".github/ISSUE_TEMPLATE.md", ".github/ISSUE_TEMPLATE.md.bk")
        logger.info("Successfully backed up files")
    except Exception as e:
        logger.error(f"Failed to back up files: {str(e)}")
        raise

def restore_files():
    logger.info("Restoring files from backup")
    try:
        # restore README.md and ISSUE_TEMPLATE.md
        shutil.move("README.md.bk", "README.md")
        shutil.move(".github/ISSUE_TEMPLATE.md.bk", ".github/ISSUE_TEMPLATE.md")
        logger.info("Successfully restored files")
    except Exception as e:
        logger.error(f"Failed to restore files: {str(e)}")
        raise

def remove_backups():
    logger.info("Removing backup files")
    try:
        # remove README.md and ISSUE_TEMPLATE.md
        os.remove("README.md.bk")
        os.remove(".github/ISSUE_TEMPLATE.md.bk")
        logger.info("Successfully removed backup files")
    except Exception as e:
        logger.error(f"Failed to remove backup files: {str(e)}")
        raise

def get_daily_date():
    # get beijing time in the format of "March 1, 2021"
    beijing_timezone = pytz.timezone('Asia/Shanghai')
    today = datetime.datetime.now(beijing_timezone)
    date_str = today.strftime("%B %d, %Y")
    logger.debug(f"Generated date string: {date_str}")
    return date_str
