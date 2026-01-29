import argparse
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from typing import Any

import pytz

from utils import (
    back_up_files,
    generate_table,
    get_daily_date,
    get_daily_papers_by_keyword_with_retries,
    get_daily_papers_by_keyword_with_retries_acm,
    get_daily_papers_by_keyword_with_retries_crossref,
    get_daily_papers_by_keyword_with_retries_ieee,
    get_daily_papers_by_keyword_with_retries_openalex,
    get_daily_papers_by_keyword_with_retries_semantic_scholar,
    remove_backups,
    restore_files,
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ai_agriculture_news.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def parse_arguments() -> Any:
    """Parse command-line arguments for the paper fetcher."""
    parser = argparse.ArgumentParser(description="AI Agriculture News Paper Fetcher")
    parser.add_argument(
        "--max-results",
        type=int,
        default=1000,
        help="Maximum number of query results from arXiv/ACM APIs for each keyword",
    )
    parser.add_argument(
        "--issues-results",
        type=int,
        default=200,
        help="Maximum number of papers to be included in the issue",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=[
            "agriculture",
            "farming",
            "crop",
            "weather",
            "climate",
            "soil",
            "plant",
            "environment",
            "sustainability",
        ],
        help="Keywords to search for papers",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="Force update even if already updated today",
    )
    parser.add_argument(
        "--include-crossref",
        action="store_true",
        help="Also fetch and include papers via CrossRef",
    )
    parser.add_argument(
        "--include-acm",
        action="store_true",
        help="Also fetch and include papers via the ACM Digital Library API",
    )
    parser.add_argument(
        "--include-openalex",
        action="store_true",
        help="Also fetch and include papers via OpenAlex",
    )
    parser.add_argument(
        "--include-ieee",
        action="store_true",
        help="Also fetch and include papers via IEEE Xplore keyword search",
    )
    parser.add_argument(
        "--include-semanticscholar",
        action="store_true",
        help="Also fetch and include papers via Semantic Scholar",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for updating the daily papers README and issue template."""
    args = parse_arguments()
    beijing_timezone = pytz.timezone("Asia/Singapore")
    current_date = datetime.now(beijing_timezone).strftime("%Y-%m-%d")

    logger.info("Starting AI Agriculture News Update Script")

    # Ensure .github directory exists
    os.makedirs(".github", exist_ok=True)

    # Check last update date
    try:
        with open("README.md") as f:
            while True:
                line = f.readline()
                if not line:
                    break
                if "Last update:" in line:
                    last_update_date = line.split(": ")[1].strip()
                    if last_update_date == current_date and not args.force_update:
                        logger.info(
                            "Already updated today! Use --force-update to override.",
                        )
                        return
                    break
    except FileNotFoundError:
        logger.info("README.md not found. Creating new file.")

    column_names = ["Title", "Link", "Abstract", "Date", "Comment"]

    try:
        back_up_files()
        logger.info("Backed up existing files")

        # write to README.md
        with open("README.md", "w") as f_rm:
            f_rm.write("# Daily Papers\n")
            f_rm.write(
                "The project automatically fetches the latest papers from arXiv "
                "and optionally from CrossRef, OpenAlex, and Semantic Scholar "
                "based on keywords.\n\n",
            )
            f_rm.write(
                "The subheadings in the README file represent the search keywords.\n\n",
            )
            f_rm.write(
                "Only the most recent articles for each keyword are "
                "retained, up to a maximum of 100 papers.\n\n",
            )
            f_rm.write(
                "You can click the 'Watch' button to receive daily email "
                "notifications.\n\n",
            )
            f_rm.write(f"Last update: {current_date}\n\n")

        # write to ISSUE_TEMPLATE.md
        with open(".github/ISSUE_TEMPLATE.md", "w") as f_is:
            f_is.write("---\n")
            f_is.write(
                f"title: Latest {args.issues_results} Papers - {get_daily_date()}\n",
            )
            f_is.write("labels: documentation\n")
            f_is.write("---\n")
            f_is.write(
                "**Please check the "
                "[Github](https://github.com/ai-agriculture-circuits-and-systems/"
                "ai_agriculture_news) page for a better reading experience and more "
                "papers.**\n\n",
            )

        for keyword in args.keywords:
            logger.info("Processing keyword: %s", keyword)
            with open("README.md", "a") as f_rm, open(
                ".github/ISSUE_TEMPLATE.md",
                "a",
            ) as f_is:
                f_rm.write(f"## {keyword}\n")
                f_is.write(f"## {keyword}\n")

                link = "AND" if len(keyword.split()) == 1 else "OR"

                # arXiv papers (always included)
                papers = get_daily_papers_by_keyword_with_retries(
                    keyword,
                    column_names,
                    args.max_results,
                    link,
                )
                if papers is None:
                    raise Exception(f"Failed to get papers for keyword: {keyword}")

                f_rm.write("### arXiv\n")
                rm_table = generate_table(papers)
                is_table = generate_table(
                    papers[: args.issues_results],
                    ignore_keys=["Abstract"],
                )

                f_rm.write(rm_table)
                f_rm.write("\n\n")
                f_is.write(is_table)
                f_is.write("\n\n")

                logger.info(
                    "Successfully processed %d arXiv papers for keyword: %s",
                    len(papers),
                    keyword,
                )

                # CrossRef papers (optional)
                if args.include_crossref:
                    logger.info("Fetching CrossRef papers for keyword: %s", keyword)
                    cr_papers = get_daily_papers_by_keyword_with_retries_crossref(
                        keyword,
                        column_names,
                        args.max_results,
                    )
                    if cr_papers:
                        f_rm.write("### CrossRef\n")
                        rm_cr_table = generate_table(cr_papers)
                        is_cr_table = generate_table(
                            cr_papers[: args.issues_results],
                            ignore_keys=["Abstract"],
                        )
                        f_rm.write(rm_cr_table)
                        f_rm.write("\n\n")
                        f_is.write(is_cr_table)
                        f_is.write("\n\n")

                # ACM papers (optional, via official API)
                if args.include_acm:
                    logger.info("Fetching ACM papers for keyword: %s", keyword)
                    acm_papers = get_daily_papers_by_keyword_with_retries_acm(
                        keyword,
                        column_names,
                        args.max_results,
                    )
                    if acm_papers:
                        f_rm.write("### ACM (Digital Library API)\n")
                        rm_acm_table = generate_table(acm_papers)
                        is_acm_table = generate_table(
                            acm_papers[: args.issues_results],
                            ignore_keys=["Abstract"],
                        )
                        f_rm.write(rm_acm_table)
                        f_rm.write("\n\n")
                        f_is.write(is_acm_table)
                        f_is.write("\n\n")

                # OpenAlex papers (optional)
                if args.include_openalex:
                    logger.info("Fetching OpenAlex papers for keyword: %s", keyword)
                    oa_papers = get_daily_papers_by_keyword_with_retries_openalex(
                        keyword,
                        column_names,
                        args.max_results,
                    )
                    if oa_papers:
                        f_rm.write("### OpenAlex\n")
                        rm_oa_table = generate_table(oa_papers)
                        is_oa_table = generate_table(
                            oa_papers[: args.issues_results],
                            ignore_keys=["Abstract"],
                        )
                        f_rm.write(rm_oa_table)
                        f_rm.write("\n\n")
                        f_is.write(is_oa_table)
                        f_is.write("\n\n")

                # Semantic Scholar papers (optional)
                if args.include_semanticscholar:
                    logger.info(
                        "Fetching Semantic Scholar papers for keyword: %s",
                        keyword,
                    )
                    ss_papers = (
                        get_daily_papers_by_keyword_with_retries_semantic_scholar(
                            keyword,
                            column_names,
                            args.max_results,
                        )
                    )
                    if ss_papers:
                        f_rm.write("### Semantic Scholar\n")
                        rm_ss_table = generate_table(ss_papers)
                        is_ss_table = generate_table(
                            ss_papers[: args.issues_results],
                            ignore_keys=["Abstract"],
                        )
                        f_rm.write(rm_ss_table)
                        f_rm.write("\n\n")
                        f_is.write(is_ss_table)
                        f_is.write("\n\n")

                # IEEE papers (optional)
                if args.include_ieee:
                    logger.info("Fetching IEEE papers for keyword: %s", keyword)
                    ieee_papers = get_daily_papers_by_keyword_with_retries_ieee(
                        keyword,
                        column_names,
                        args.max_results,
                    )
                    if ieee_papers:
                        f_rm.write("### IEEE (Xplore)\n")
                        rm_ieee_table = generate_table(ieee_papers)
                        is_ieee_table = generate_table(
                            ieee_papers[: args.issues_results],
                            ignore_keys=["Abstract"],
                        )
                        f_rm.write(rm_ieee_table)
                        f_rm.write("\n\n")
                        f_is.write(is_ieee_table)
                        f_is.write("\n\n")

                time.sleep(5)  # avoid being blocked by remote APIs

        # Create dated archive in data folder
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)

        archive_filename = f"{current_date}.md"
        archive_path = os.path.join(data_dir, archive_filename)
        shutil.copy2("README.md", archive_path)
        logger.info("Created archive: %s", archive_path)

        remove_backups()
        logger.info("Script completed successfully!")

    except Exception as exc:  # noqa: BLE001
        logger.error("An error occurred: %s", exc)
        restore_files()
        raise


if __name__ == "__main__":
    main()
