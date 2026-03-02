# Validity Everest API - CSV Batch Domain Query Tool

A robust and automated Python script designed to batch query domain names against the Validity Everest API. This tool helps email deliverability professionals and marketers quickly gather Email Service Provider (ESP) intelligence and estimated sending volumes for large lists of domains.

## ✨ Key Features

* **Smart CSV Parsing:** Automatically detects the domain column in your CSV files. Supports multiple file encodings (UTF-8, GBK, etc.) for seamless reading.
* **Automated Data Aggregation:** Queries the main domain, automatically fetches all associated subdomains recognized by the Everest API, and aggregates their sending metrics.
* **Competitor Intelligence:** Retrieves and calculates the market share (percentage) of different ESPs used by the queried domains.
* **Resume Capability (Fault Tolerance):** Automatically saves query progress to a local `.progress.json` file. If the script is interrupted, you can restart it without re-querying previously completed rows, saving API limits and time.
* **Rate Limiting Built-in:** Gracefully handles API rate limits with customizable sleep intervals and automatic retry logic.

## 🛠 Prerequisites

* Python 3.6+
* A valid Validity Everest API Key

## 📦 Installation

Clone this repository and install the required dependencies using `pip`:

```bash
pip install -r requirements.txt
(Note: The script features a self-healing dependency mechanism. If you run it directly without installing requirements, it will attempt to install requests automatically.)

🚀 Usage
Execute the script via your terminal:

Bash
python everest_query.py
Follow the interactive prompts:

Paste your Validity Everest API Key.

Provide the path to your Input CSV file.

Confirm the automatically detected domain column.

📊 Output Format
The script will generate a new CSV file named [original_filename]_result.csv. It preserves your original data and appends the following 4 intelligence columns:

ESP: Semicolon-separated list of Email Service Providers detected.

ESP占比 / ESP Percentage: The corresponding usage percentage for each ESP.

存在发信的域名 / Active Subdomains: A list of subdomains and related domains that have recorded sending activity.

发信量估计 / Estimated Volume: The aggregated estimated email volume for the matched domains.

⚠️ Disclaimer
This is an unofficial third-party utility. Please ensure compliance with Validity Everest's API Terms of Service when using this tool.
