import sys
import time
import pytz
import os
import shutil
import logging
import argparse
from datetime import datetime

from utils import get_daily_papers_by_keyword_with_retries, generate_table, back_up_files,\
    restore_files, remove_backups, get_daily_date

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_agriculture_news.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def parse_arguments():
    parser = argparse.ArgumentParser(description='AI Agriculture News Paper Fetcher')
    parser.add_argument('--max-results', type=int, default=1000,
                      help='Maximum number of query results from arXiv API for each keyword')
    parser.add_argument('--issues-results', type=int, default=200,
                      help='Maximum number of papers to be included in the issue')
    parser.add_argument('--keywords', nargs='+', default=[
        "agriculture", "farming", "crop", "weather", "climate", 
        "soil", "plant", "environment", "sustainability"
    ], help='Keywords to search for papers')
    parser.add_argument('--force-update', action='store_true',
                      help='Force update even if already updated today')
    return parser.parse_args()

def main():
    args = parse_arguments()
    beijing_timezone = pytz.timezone('Asia/Singapore')
    current_date = datetime.now(beijing_timezone).strftime("%Y-%m-%d")
    
    logger.info("Starting AI Agriculture News Update Script")
    
    # Ensure .github directory exists
    os.makedirs(".github", exist_ok=True)
    
    # Check last update date
    try:
        with open("README.md", "r") as f:
            while True:
                line = f.readline()
                if "Last update:" in line: 
                    last_update_date = line.split(": ")[1].strip()
                    if last_update_date == current_date and not args.force_update:
                        logger.info("Already updated today! Use --force-update to override.")
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
            f_rm.write("The project automatically fetches the latest papers from arXiv based on keywords.\n\n")
            f_rm.write("The subheadings in the README file represent the search keywords.\n\n")
            f_rm.write("Only the most recent articles for each keyword are retained, up to a maximum of 100 papers.\n\n")
            f_rm.write("You can click the 'Watch' button to receive daily email notifications.\n\n")
            f_rm.write(f"Last update: {current_date}\n\n")
        
        # write to ISSUE_TEMPLATE.md
        with open(".github/ISSUE_TEMPLATE.md", "w") as f_is:
            f_is.write("---\n")
            f_is.write(f"title: Latest {args.issues_results} Papers - {get_daily_date()}\n")
            f_is.write("labels: documentation\n")
            f_is.write("---\n")
            f_is.write("**Please check the [Github](https://github.com/ai-agriculture-circuits-and-systems/ai_agriculture_news) page for a better reading experience and more papers.**\n\n")
        
        for keyword in args.keywords:
            logger.info(f"Processing keyword: {keyword}")
            with open("README.md", "a") as f_rm, open(".github/ISSUE_TEMPLATE.md", "a") as f_is:
                f_rm.write(f"## {keyword}\n")
                f_is.write(f"## {keyword}\n")
                
                link = "AND" if len(keyword.split()) == 1 else "OR"
                papers = get_daily_papers_by_keyword_with_retries(keyword, column_names, args.max_results, link)
                
                if papers is None:
                    raise Exception(f"Failed to get papers for keyword: {keyword}")
                
                rm_table = generate_table(papers)
                is_table = generate_table(papers[:args.issues_results], ignore_keys=["Abstract"])
                
                f_rm.write(rm_table)
                f_rm.write("\n\n")
                f_is.write(is_table)
                f_is.write("\n\n")
                
                logger.info(f"Successfully processed {len(papers)} papers for keyword: {keyword}")
                time.sleep(5)  # avoid being blocked by arXiv API
        
        # Create dated archive in data folder
        data_dir = "data"
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
        
        archive_filename = f"{current_date}.md"
        archive_path = os.path.join(data_dir, archive_filename)
        shutil.copy2("README.md", archive_path)
        logger.info(f"Created archive: {archive_path}")
        
        remove_backups()
        logger.info("Script completed successfully!")
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        restore_files()
        raise

if __name__ == "__main__":
    main()
