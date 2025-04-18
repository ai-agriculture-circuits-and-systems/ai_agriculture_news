import os
import time
import pytz
import shutil
import datetime
import logging
from typing import List, Dict
import urllib, urllib.request

import feedparser
from easydict import EasyDict

# Set up logger
logger = logging.getLogger(__name__)

def remove_duplicated_spaces(text: str) -> str:
    return " ".join(text.split())

def request_paper_with_arXiv_api(keyword: str, max_results: int, link: str = "OR") -> List[Dict[str, str]]:
    assert link in ["OR", "AND"], "link should be 'OR' or 'AND'"
    keyword = "\"" + keyword + "\""
    url = "http://export.arxiv.org/api/query?search_query=ti:{0}+{2}+abs:{0}&max_results={1}&sortBy=lastUpdatedDate".format(keyword, max_results, link)
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")
    
    logger.info(f"Requesting papers from arXiv API for keyword: {keyword}")
    try:
        response = urllib.request.urlopen(url).read().decode('utf-8')
        feed = feedparser.parse(response)
        logger.info(f"Successfully retrieved {len(feed.entries)} papers from arXiv API")
    except Exception as e:
        logger.error(f"Failed to fetch papers from arXiv API: {str(e)}")
        raise

    # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Date
    papers = []
    for entry in feed.entries:
        try:
            entry = EasyDict(entry)
            paper = EasyDict()

            # title
            paper.Title = remove_duplicated_spaces(entry.title.replace("\n", " "))
            # abstract
            paper.Abstract = remove_duplicated_spaces(entry.summary.replace("\n", " "))
            # authors
            paper.Authors = [remove_duplicated_spaces(_["name"].replace("\n", " ")) for _ in entry.authors]
            # link
            paper.Link = remove_duplicated_spaces(entry.link.replace("\n", " "))
            # tags
            paper.Tags = [remove_duplicated_spaces(_["term"].replace("\n", " ")) for _ in entry.tags]
            # comment
            paper.Comment = remove_duplicated_spaces(entry.get("arxiv_comment", "").replace("\n", " "))
            # date
            paper.Date = entry.updated

            papers.append(paper)
        except Exception as e:
            logger.warning(f"Failed to process paper entry: {str(e)}")
            continue
    
    logger.info(f"Successfully processed {len(papers)} papers")
    return papers

def filter_tags(papers: List[Dict[str, str]], target_fileds: List[str]=["cs", "stat"]) -> List[Dict[str, str]]:
    logger.info(f"Filtering papers by tags: {target_fileds}")
    # filtering tags: only keep the papers in target_fileds
    results = []
    for paper in papers:
        tags = paper.Tags
        for tag in tags:
            if tag.split(".")[0] in target_fileds:
                results.append(paper)
                break
    logger.info(f"Filtered papers: {len(results)} out of {len(papers)} papers kept")
    return results

def get_daily_papers_by_keyword_with_retries(keyword: str, column_names: List[str], max_result: int, link: str = "OR", retries: int = 6) -> List[Dict[str, str]]:
    logger.info(f"Attempting to get papers for keyword '{keyword}' with {retries} retries")
    for attempt in range(retries):
        try:
            papers = get_daily_papers_by_keyword(keyword, column_names, max_result, link)
            if len(papers) > 0:
                logger.info(f"Successfully retrieved {len(papers)} papers on attempt {attempt + 1}")
                return papers
            else:
                logger.warning(f"Received empty list on attempt {attempt + 1}, retrying in 30 minutes...")
                time.sleep(60 * 30)  # wait for 30 minutes
        except Exception as e:
            logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
            if attempt < retries - 1:
                logger.info("Waiting 30 minutes before retry...")
                time.sleep(60 * 30)
    
    logger.error("Failed to get papers after all retry attempts")
    return None

def get_daily_papers_by_keyword(keyword: str, column_names: List[str], max_result: int, link: str = "OR") -> List[Dict[str, str]]:
    logger.info(f"Getting papers for keyword: {keyword}")
    # get papers
    papers = request_paper_with_arXiv_api(keyword, max_result, link)
    # NOTE filtering tags: only keep the papers in cs field
    papers = filter_tags(papers)
    # select columns for display
    papers = [{column_name: paper[column_name] for column_name in column_names} for paper in papers]
    logger.info(f"Retrieved {len(papers)} papers after filtering and column selection")
    return papers

def generate_table(papers: List[Dict[str, str]], ignore_keys: List[str] = []) -> str:
    logger.info(f"Generating table for {len(papers)} papers")
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
        except Exception as e:
            logger.warning(f"Failed to format paper: {str(e)}")
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
