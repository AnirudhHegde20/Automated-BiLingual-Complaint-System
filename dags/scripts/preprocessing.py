import os
import re
import io
import logging
import polars as pl
import pandas as pd
from fast_langdetect import detect_language
from bloom_filter2 import BloomFilter
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
from google.oauth2 import service_account
DRY_RUN = True

# Defining a custom logger
def get_custom_logger():
    # Customer logs are stored in the below path
    log_path = os.path.join(os.path.dirname(__file__), "../../logs/application_logs/preprocessing_log.txt")
    custom_logger = logging.getLogger("preprocessing_logger")
    custom_logger.setLevel(logging.INFO)
    
    # Avoid default logs by setting propagate to False
    custom_logger.propagate = False

    # Set up a file handler for the custom logger
    if not custom_logger.handlers:
        file_handler = logging.FileHandler(log_path, mode="a")
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(funcName)s - %(message)s")
        file_handler.setFormatter(formatter)
        custom_logger.addHandler(file_handler)
    
    return custom_logger

def load_data() -> str:
    """
    Load the JPMorgan Chase complaints dataset in Parquet format.
    Returns:
        str: Serialized dataset in JSON format.
    Raises:
        Exception: If there is an error loading the dataset.
    """
    logger = get_custom_logger()  # Get the custom logger instance
    logger.info("Starting data load process.")
    #data_path = os.path.join(os.path.dirname(__file__), "../../data/dataset.parquet")

    # File is hosted on Google Cloud Storage (GCS), reading data from GCP
    data_path ="https://storage.googleapis.com/mlops-group6-raw-data/dataset.parquet"
    try:
        # Load the dataset and serialize it
        dataset = pl.read_parquet(data_path)
        
        # Log the number of records loaded
        logger.info(f"Total records loaded: {len(dataset)}")

        # Serialize the dataset to JSON format for further processing
        dataset = dataset.serialize(format="json")
        
        logger.info("Data load and serialization successful.")
        return dataset
    except Exception as error:
        # Log any errors encountered during loading
        logger.error(f"Error loading dataset: {error}")
        raise Exception("Error With Dataset Loading")


def filter_records_by_word_count_and_date(dataset: str, min_word_length: int) -> str:
    """
    Remove records from the dataset that do not meet the minimum word count
    in the 'complaint' column.
    Args:
        dataset (str): Serialized dataset in JSON format.
        min_word_length (int): Minimum word count required for each record.
    Returns:
        str: Serialized dataset in JSON format with records removed if they
             have fewer words than the specified minimum.
    """
    logger = get_custom_logger()
    logger.info(f"Filtering records by word count, minimum words required: {min_word_length}")
    
    # Deserialize the dataset
    dataset = pl.DataFrame.deserialize(io.StringIO(dataset), format="json")

    # Log the total number of records before filtering
    logger.info(f"Total records before filtering: {len(dataset)}")

    # Filter records based on the minimum word count and remove the count column
    dataset = (
    dataset.with_columns(
        num_words=pl.col("complaint").str.split(" ").list.len()
    )
    .filter(pl.col("num_words") > min_word_length)
    .drop("num_words")
    .filter(
        (pl.col("date_received") >= pl.date(2015, 3, 19)) &
        (pl.col("date_received") <= pl.date(2024, 7, 28))
    )
)

    # Log count after date filtering
    logger.info(f"Records after date filtering: {len(dataset)}")
    
    # Serialize and return the filtered dataset
    logger.info("Word count and date filtering complete.")
    
    # Serialize and return the filtered dataset
    return dataset.serialize(format="json")


def filter_records_by_language(dataset: str) -> str:
    """
    Detect the language of each complaint in the dataset and filter out records
    that do not meet the specified language criteria ('HI' or 'EN').
    Args:
        dataset (str): Serialized dataset in JSON format.
    Returns:
        str: Serialized dataset in JSON format with records filtered to only
             include specified languages.
    """
    logger = get_custom_logger()
    logger.info("Starting language filtering for 'HI' and 'EN' languages.")
    
    # Deserialize the dataset
    dataset = pl.DataFrame.deserialize(io.StringIO(dataset), format="json")

     # Log the total number of records before language detection
    logger.info(f"Total records before language filtering: {len(dataset)}")

    # Perform language detection with multi-threading
    language_detected = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sentence = {
            executor.submit(detect_language, re.sub(r'\n', '', sentence)): sentence
            for sentence in dataset['complaint'].to_list()
        }

        # Collect results as they complete
        for future in as_completed(future_to_sentence):
            language_detected.append(future.result())

    # Add language column to dataset and filter based on language criteria
    dataset = (
        dataset.with_columns(pl.Series(name="language", values=language_detected))
        .filter(pl.col("language").is_in(["HI", "EN"]))
        .drop(["language"])
    )

    # Log the total number of records after language filtering
    logger.info(f"Records after language filtering (HI/EN only): {len(dataset)}")
    
    # Serialize and return the filtered dataset
    logger.info("Language filtering complete.")
    
    # Serialize and return the filtered dataset
    return dataset.serialize(format="json")


def aggregate_filtered_task(dataset_a: str, dataset_b: str) -> None:
    """
    Aggregate two datasets by joining them on 'complaint_id' and selecting
    specific columns. The result is saved to a specified parquet file.
    Args:
        dataset_a (str): Serialized first dataset in JSON format.
        dataset_b (str): Serialized second dataset in JSON format.
    """
    logger = get_custom_logger()
    logger.info("Starting dataset aggregation.")
    
    output_path = os.path.join(
        os.path.dirname(__file__),
        "../../data/preprocessed_dataset.parquet",
    )

    # Deserialize datasets and perform an inner join on 'Complaint ID'
    dataset_a = pl.DataFrame.deserialize(io.StringIO(dataset_a), format="json")
    dataset_b = pl.DataFrame.deserialize(io.StringIO(dataset_b), format="json")
    logger.info(f"Records in dataset A before joining: {len(dataset_a)}")
    logger.info(f"Records in dataset B before joining: {len(dataset_b)}")

    # Join datasets and select specified columns
    selected_columns = [
        "complaint_id",
        "date_received",
        "date_resolved",
        "time_resolved_in_days",
        "complaint",
        "complaint_hindi",
        "product",
        "department",
        "sub_product",
        "issue",
        "sub_issue",
        "company",
        "state",
        "zipcode",
        "company_response_consumer",
        "consumer_consent_provided",
        "submitted_via",
        "date_sent_to_company",
        "timely_response",
        "consumer_disputed",
    ]
    dataset_joined = dataset_a.join(dataset_b, on="complaint_id", how="inner").select(
        selected_columns
    )

    # Log record count after joining
    logger.info(f"Records after joining datasets on 'complaint_id': {len(dataset_joined)}")

    # Write the output to the specified parquet file
    dataset_joined.write_parquet(output_path)
    logger.info(f"Dataset aggregation complete and saved to file at: {output_path}")


def data_cleaning() -> str:
    """
    Clean the dataset by lowercasing complaint narratives, removing special characters,
    removing duplicates, and dropping records with null values in key columns.
    Returns:
        str: Serialized cleaned dataset in JSON serialized format.
    """
    logger = get_custom_logger()
    logger.info("Starting data cleaning.")
    
    # Define the data path and read the dataset
    data_path = os.path.join(
        os.path.dirname(__file__),
        "../../data/preprocessed_dataset.parquet",
    )
    dataset = pl.read_parquet(data_path)

    # Log the initial record count
    logger.info(f"Total records before cleaning: {len(dataset)}")

    # Lowercase complaint narratives
    dataset = dataset.with_columns(pl.col("complaint").str.to_lowercase())

    # Remove special characters from 'complaint' column
    dataset = dataset.with_columns(
        pl.col("complaint").map_elements(
            lambda x: re.sub(r"[^A-Za-z0-9\s]", "", x), return_dtype=pl.Utf8
        )
    )

    logger.info("Removed special characters from complaint narratives.")

    # Remove duplicate records based on specific columns
    dataset = dataset.unique(
        subset=["product", "complaint"],
        maintain_order=True,
    )



    # Drop records with nulls in specified columns
    dataset = dataset.drop_nulls(
        subset=["product", "department", "complaint"]
    )

    # Log the final cleaned record count
    logger.info(f"Data cleaning complete. Cleaned records count: {len(dataset)}")
    
    # Serialize and return the cleaned dataset
    return dataset.serialize(format="json")


def remove_abusive_data(dataset: str, abuse_placeholder: str = "<abusive_data>") -> str:
    """
    Remove abusive words from 'complaint' column in the dataset,
    replacing them with a specified placeholder. The cleaned dataset is saved to a
    predefined output path.
    Args:
        dataset (str): Serialized dataset in JSON format.
        abuse_placeholder (str): Placeholder to replace abusive words.
    Returns:
        str: Serialized dataset with abusive words removed.
    """
    logger = get_custom_logger()
    logger.info("Starting abusive data filtering.")
    
    # Define paths for input and output
    output_path = os.path.join(
        os.path.dirname(__file__),
        "../../data/preprocessed_dataset.parquet",
    )
    abusive_words_path = "https://storage.googleapis.com/mlops-group6-raw-data/profanity_bank_dataset.parquet"

    # Deserialize the dataset
    dataset = pl.DataFrame.deserialize(io.StringIO(dataset), format="json")
    logger.info(f"Total records before abusive word filtering: {len(dataset)}")

    # Set up Bloom Filter for abusive words
    profane_set = set()
    profanity_bloom = BloomFilter(max_elements=200_000, error_rate=0.01)

    # Load abusive words
    abusive_words = pl.read_parquet(abusive_words_path)["profanity"].to_list()
    logger.info(f"Total abusive words loaded: {len(abusive_words)}")

    for word in abusive_words:
        profanity_bloom.add(word)
        profane_set.add(word)

    # Tokenize and clean complaints
    tokenized_complaints = dataset.with_columns(pl.col("complaint").str.split(" "))[ "complaint" ].to_list()

    cleaned_records = []
    for record in tokenized_complaints:
        clean_record = [
            w if w not in profanity_bloom or w not in profane_set else abuse_placeholder
            for w in record
        ]
        cleaned_records.append(" ".join(clean_record))


    # Add the cleaned complaints to the dataset
    dataset = dataset.with_columns(
        pl.Series(name="abuse_free_complaints", values=cleaned_records)
    )

    logger.info("Abusive data filtering complete. Saving results to file.")
    
    # Save the processed dataset to output path
    dataset.write_parquet(output_path)
    return output_path   

def insert_data_to_bigquery(file_path: str):

    if DRY_RUN:
        return  # Insertion in BigQuery requires Credentials, which will not be uploaded to Github     

    project_id = 'bilingualcomplaint-system'
    dataset_id = 'MLOps'
    table_id = 'preprocessed_data'
    

    script_dir = os.path.dirname(os.path.abspath(__file__))  # Current script directory
    keys_path = os.path.join(script_dir, "..", "keys", "service-account.json")
    credentials = service_account.Credentials.from_service_account_file(keys_path)
    
    # Initialize BigQuery client with credentials and project ID
    client = bigquery.Client(credentials=credentials, project=project_id)
    
    dataset = pl.read_parquet(file_path)
    df = dataset.to_pandas()

    # Explicitly set `date_sent_to_company` as a string
    if "date_sent_to_company" in df.columns:
        df["date_sent_to_company"] = df["date_sent_to_company"].astype(str)
    
    if "abuse_free_complaints" in df.columns:
        df["complaint"] = df["abuse_free_complaints"]  # Overwrite `complaint` column
        df = df.drop(columns=["abuse_free_complaints"])  # Drop `abuse_free_complaints` to avoid schema issues  
    
    # Set the table reference
    table_ref = f"{project_id}.{dataset_id}.{table_id}"

    # Configure load job
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,  # Options: WRITE_TRUNCATE, WRITE_APPEND, WRITE_EMPTY
    )

    # Start the job to upload data
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config) 
    # Wait for the job to complete
    job.result()