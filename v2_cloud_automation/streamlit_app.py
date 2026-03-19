import streamlit as st
from tenacity import retry, stop_after_attempt, wait_exponential
import gspread
from googleapiclient.discovery import build

# Cache credentials and service
@st.cache_resource
def get_gspread_service(credentials):
    return gspread.authorize(credentials)

@st.cache_resource
def get_google_api_service(api_name, api_version, credentials):
    return build(api_name, api_version, credentials=credentials)

# Retry strategy for Google API calls
@retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_google_api(service_function, *args, **kwargs):
    return service_function(*args, **kwargs)

# Example of using the retry decorator
@st.cache_resource
def fetch_data_from_google_sheet(sheet_id, range_name, credentials):
    service = get_gspread_service(credentials)
    sheet = call_google_api(service.open_by_key, sheet_id)
    data = call_google_api(sheet.get_worksheet, 0).get(range_name)
    return data