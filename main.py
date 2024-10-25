from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import List
import os
import asyncio
import aiohttp
import logging
from dotenv import load_dotenv
import psutil
import fitz
import io
import datetime

# Import Azure Blob Storage libraries
from azure.storage.blob.aio import BlobServiceClient
from azure.storage.blob import generate_blob_sas, BlobSasPermissions

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:3000",
    "https://yourvercelapp.vercel.app",  # Replace with your Vercel app URL
    # Add any other origins that need to access your API
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow these origins
    allow_credentials=True,
    allow_methods=["*"],    # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],    # Allow all headers
)


# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)


class PDFUrl(BaseModel):
    url: HttpUrl


# Load Azure Blob Storage credentials
AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
if not AZURE_STORAGE_CONNECTION_STRING:
    raise Exception("Azure Storage connection string not found in environment variables.")

# Initialize Azure Blob Storage client
blob_service_client = BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)


def log_resource_usage(stage):
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    cpu_percent = process.cpu_percent(interval=None)
    logging.info(f"{stage} - Memory Usage: {mem_info.rss / (1024 * 1024):.2f} MB, CPU Usage: {cpu_percent}%")


async def download_pdf(url: str) -> bytes:
    try:
        url = str(url)
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True) as response:
                logging.info(f"Response status: {response.status}")
                logging.info(f"Response headers: {response.headers}")
                if response.status != 200:
                    raise HTTPException(status_code=400,
                                        detail=f"Failed to download PDF. Status code: {response.status}")
                content_type = response.headers.get('Content-Type', '')
                logging.info(f"Content-Type: {content_type}")
                if 'pdf' not in content_type.lower():
                    raise HTTPException(status_code=400,
                                        detail=f"URL does not point to a PDF file. Content-Type: {content_type}")
                pdf_bytes = await response.read()
                MAX_PDF_SIZE = 100 * 1024 * 1024  # 10 MB
                if len(pdf_bytes) > MAX_PDF_SIZE:
                    raise HTTPException(status_code=400, detail="PDF file is too large.")
                return pdf_bytes
    except aiohttp.ClientError as e:
        logging.error(f"Client error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail="Client error occurred while downloading PDF.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected error occurred.")


async def convert_pdf_to_images(pdf_bytes: bytes) -> List[bytes]:
    try:
        log_resource_usage("Before Conversion")
        image_bytes_list = []
        MAX_PAGE_COUNT = 3000  # Limit the number of pages to process
        DPI = 100  # Set DPI to reduce resource usage
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            page_count = doc.page_count
            logging.info(f"PDF has {page_count} pages.")
            if page_count > MAX_PAGE_COUNT:
                raise HTTPException(
                    status_code=400,
                    detail=f"PDF has too many pages ({page_count}). Maximum allowed is {MAX_PAGE_COUNT}."
                )
            for page_num in range(min(page_count, MAX_PAGE_COUNT)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=DPI)
                image_bytes = pix.tobytes("png")
                image_bytes_list.append(image_bytes)
        log_resource_usage("After Conversion")
        return image_bytes_list
    except Exception as e:
        logging.error(f"Error converting PDF to images: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error converting PDF to images.")


async def upload_image_to_azure_blob(image_bytes: bytes, filename: str) -> str:
    try:
        container_name = os.getenv("AZURE_CONTAINER_NAME")
        if not container_name:
            raise Exception("Azure container name not found in environment variables.")

        # Get a client to interact with the specified container
        container_client = blob_service_client.get_container_client(container_name)
        # Create the container if it does not exist
        try:
            await container_client.create_container()
        except Exception as e:
            logging.info(f"Container may already exist or error creating container: {e}")

        # Get a blob client
        blob_client = container_client.get_blob_client(filename)

        # Upload the image
        await blob_client.upload_blob(image_bytes, overwrite=True)

        # Parse connection string to get account name and key
        def parse_connection_string(connection_string):
            parts = connection_string.split(';')
            conn_dict = {}
            for part in parts:
                key, value = part.split('=', 1)
                conn_dict[key] = value
            return conn_dict

        conn_params = parse_connection_string(AZURE_STORAGE_CONNECTION_STRING)
        account_name = conn_params.get('AccountName')
        account_key = conn_params.get('AccountKey')

        if not account_name or not account_key:
            raise Exception("Account name or key not found in connection string.")

        # Generate a SAS token for the blob
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=container_name,
            blob_name=filename,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.datetime.utcnow() + datetime.timedelta(hours=24)  # Adjust expiry as needed
        )

        # Construct the full URL to the blob including the SAS token
        blob_url = f"{blob_client.url}?{sas_token}"
        return blob_url
    except Exception as e:
        logging.error(f"Error uploading image to Azure Blob Storage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error uploading images.")


@app.post("/convert-pdf")
async def convert_pdf(pdf: PDFUrl):
    pdf_bytes = await download_pdf(str(pdf.url))
    image_bytes_list = await convert_pdf_to_images(pdf_bytes)

    # Upload images asynchronously
    upload_tasks = [
        upload_image_to_azure_blob(image_bytes, f"page{idx + 1}.png")
        for idx, image_bytes in enumerate(image_bytes_list)
    ]
    image_urls = await asyncio.gather(*upload_tasks)

    if not image_urls:
        raise HTTPException(status_code=500, detail="No images were generated.")

    return {"images": image_urls}


@app.get("/health")
async def health():
    return {"status": "ok"}
