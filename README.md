# PDF to PNG Conversion API

An API that converts PDF files to PNG images. This API ingests a URL to a PDF file, converts each page of the PDF into a PNG image, stores the images in Azure Blob Storage, and returns a list of URLs pointing to the PNG images.

The application is built with FastAPI and containerized using Docker for deployment on Azure. It leverages Azure services like Azure Container Registry and Azure App Service for hosting, and Azure Blob Storage for storing the converted images.

## Features

- **PDF to PNG Conversion:** Converts each page of a PDF document to a PNG image.
- **Azure Blob Storage Integration:** Stores the converted images in Azure Blob Storage.
- **Asynchronous Processing:** Utilizes asynchronous programming for efficient handling of I/O-bound operations.
- **RESTful API:** Provides an easy-to-use API endpoint for PDF conversion.
- **Dockerized Deployment:** Containerized with Docker for easy deployment to cloud platforms like Azure.

## Performance Notes

Performance may vary based on the size and complexity of the PDF file and the DPI setting used for conversion.

- **100 DPI:** An 81-page PDF with tables and images takes approximately 18 seconds to process.
- **200 DPI:** The same PDF takes approximately 43 seconds.
- **250 DPI:** Processing time increases to approximately 1 minute and 15 seconds.

Note: Increasing the DPI improves image quality but also increases processing time and resource usage. Adjust the DPI according to your needs and resource constraints.
