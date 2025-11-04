# ChatLog Viewer - Standalone Application

A standalone tool for viewing and exploring ChatGPT/Grok/Claude export data with all metadata. This application extracts and displays conversations, messages, feedback, timeline events, and geolocation data from ChatGPT export files.

## Features

- **Full Metadata Extraction**: Extracts ALL metadata from ChatGPT export files (browser info, geolocation, timestamps, etc.)
- **Multiple Views**:
  - **List View**: Browse all conversations with search and pagination
  - **Timeline View**: Chronological view of all events across conversations
  - **TTL Data View**: Authentication and geolocation/IP data from TTL exports
  - **Content Filter Events**: View messages that triggered content filters
- **Import Support**:
  - JSON exports from ChatGPT (conversations.json, message_feedback.json, etc.)
  - HTML exports from ChatGPT (and other AI services like Grok, Anthropic, Perplexity)
- **Export Functionality**: Export selected conversations or messages as JSON
- **Local SQLite Database**: All data stored locally in `chatlog_viewer.db`

## System Requirements

- Python 3.8 or higher
- pip (Python package installer)
- 100MB+ free disk space

## Installation

### macOS

1. **Check Python Installation**
   ```bash
   python3 --version
   ```
   If Python is not installed, install it from [python.org](https://www.python.org/downloads/) or using Homebrew:
   ```bash
   brew install python3
   ```

2. **Navigate to ChatLog_standalone Directory**
   ```bash
   cd /path/to/ChatLog_standalone
   ```

3. **Create Virtual Environment (Recommended)**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

4. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Create Chatlog Directory**
   ```bash
   mkdir -p chatlog
   ```

### Windows

1. **Check Python Installation**
   - Open Command Prompt or PowerShell
   - Run: `python --version` or `py --version`
   - If Python is not installed, download from [python.org](https://www.python.org/downloads/)
   - **Important**: During installation, check "Add Python to PATH"

2. **Navigate to ChatLog_standalone Directory**
   ```cmd
   cd C:\path\to\ChatLog_standalone
   ```

3. **Create Virtual Environment (Recommended)**
   ```cmd
   python -m venv venv
   venv\Scripts\activate
   ```
   Or with PowerShell:
   ```powershell
   python -m venv venv
   venv\Scripts\Activate.ps1
   ```
   If you get an execution policy error in PowerShell, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

4. **Install Dependencies**
   ```cmd
   pip install -r requirements.txt
   ```

5. **Create Chatlog Directory**
   ```cmd
   mkdir chatlog
   ```

## Running the Application

### macOS

1. **Activate Virtual Environment (if using one)**
   ```bash
   source venv/bin/activate
   ```

2. **Start the Server**
   ```bash
   uvicorn app.main:app --reload --port 8002
   ```

3. **Open Browser**
   Navigate to: `http://localhost:8002`

### Windows

1. **Activate Virtual Environment (if using one)**
   ```cmd
   venv\Scripts\activate
   ```

2. **Start the Server**
   ```cmd
   uvicorn app.main:app --reload --port 8002
   ```

3. **Open Browser**
   Navigate to: `http://localhost:8002`

## Usage

### Importing Data

1. **Prepare Your Export Files**
   - Place your ChatGPT export folders in the `chatlog/` directory
   - Each export folder should contain:
     - `conversations.json` (required)
     - `message_feedback.json` (optional)
     - `user.json` (optional)
     - `model_comparisons.json` (optional)

2. **Import JSON Exports**
   - Click "Start Import" button in the web interface
   - The app will scan all subfolders in `chatlog/` and import them
   - Duplicate conversations (based on conversation_id) are automatically skipped

3. **Import HTML Exports**
   - Place HTML files in `chatlog/HTMLS/` directory
   - Optionally organize by service: `chatlog/HTMLS/chatgpt/`, `chatlog/HTMLS/grok/`, etc.
   - Click "Import HTML Files" button
   - Supports ChatGPT, Grok, Anthropic Claude, and Perplexity HTML exports

### Viewing Data

- **List View**: Browse all conversations with search and filters
- **Timeline View**: See chronological events across all conversations
- **TTL Data**: View authentication sessions with geolocation and IP data
- **Content Filter Events**: Find messages that triggered safety filters

### Exporting Data

- Select conversations using checkboxes and click "Export Selected"
- Or open a conversation detail view and export individual messages

## Directory Structure

```
ChatLog_standalone/
├── app/                    # Backend application code
│   ├── __init__.py
│   ├── main.py            # FastAPI application entry point
│   ├── api.py             # API endpoints
│   ├── models.py          # Database models
│   ├── database_service.py
│   ├── import_service.py
│   ├── html_import.py
│   └── ttl_import.py
├── frontend/              # Frontend files
│   ├── index.html         # Main HTML template
│   └── app.js             # JavaScript application code
├── chatlog/               # Your export data goes here
│   ├── [export_folder_1]/
│   │   ├── conversations.json
│   │   └── ...
│   └── HTMLS/
│       ├── chatgpt/
│       └── ...
├── chatlog_viewer.db      # SQLite database (created automatically)
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Troubleshooting

### Port Already in Use

If port 8002 is already in use, specify a different port:
```bash
uvicorn app.main:app --reload --port 8003
```

### Database Issues

If you encounter database errors:
- Delete `chatlog_viewer.db` and restart the application
- The database will be recreated automatically

### Import Errors

- Check that your export folders are in the `chatlog/` directory
- Ensure JSON files are valid (not corrupted)
- Check the browser console for error messages

### Python Not Found (Windows)

- Make sure Python is added to PATH during installation
- Try using `py` instead of `python` in commands
- Reinstall Python and check "Add Python to PATH" option

### Virtual Environment Issues

If you have issues with the virtual environment:
- Delete the `venv` folder and recreate it
- Make sure you're using the correct Python version

## Stopping the Server

- Press `Ctrl+C` in the terminal/command prompt
- Deactivate virtual environment (optional): `deactivate`

## Advanced Usage

### Custom Database Location

You can specify a custom database path by modifying `database_service.py` or passing it when initializing the service.

### Custom Chatlog Directory

You can specify a custom chatlog directory by modifying `import_service.py` or passing it when initializing the service.

### Running Without Virtual Environment

You can install dependencies globally (not recommended):
```bash
pip install -r requirements.txt
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review error messages in the browser console (F12)
3. Check terminal/command prompt output for backend errors

## Notes

- The database file (`chatlog_viewer.db`) stores all imported data locally
- Data is never sent to external servers - everything runs locally
- HTML imports require BeautifulSoup4 and lxml (included in requirements.txt)
- The application automatically creates necessary directories on first run

