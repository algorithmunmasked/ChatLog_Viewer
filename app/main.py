"""
Standalone FastAPI application for ChatGPT Viewer
Run with: uvicorn app.main:app --reload --port 8002
Or from project root: uvicorn app.main:app --reload --port 8002
"""
import os
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

from .api import router

# Create FastAPI app
app = FastAPI(title="ChatGPT Log Viewer", version="1.0.0")

# Include router
app.include_router(router)

# Setup templates and static files
# Get the project root (parent of app directory)
# __file__ is at: app/main.py
# parent once: app/
# parent twice: project root (ChatLog_standalone/)
project_root = Path(__file__).parent.parent
frontend_path = project_root / "frontend"

# Mount static files
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# Setup Jinja2 templates
templates = None
if frontend_path.exists():
    templates = Environment(
        loader=FileSystemLoader(str(frontend_path)),
        autoescape=select_autoescape(['html', 'xml'])
    )
    
    # Add url_for function to template globals (for static file URLs)
    def url_for_static(name: str, path: str = "", **kwargs) -> str:
        """Generate URL for static files"""
        if name == 'static':
            return f"/static/{path.lstrip('/')}"
        return "#"
    
    templates.globals['url_for'] = url_for_static

def template_response(template_name: str, request: Request, **kwargs):
    """Render a template"""
    if not templates:
        return HTMLResponse(content=f"Template directory not found: {frontend_path}")
    
    template = templates.get_template(template_name)
    context = {"request": request}
    context.update(kwargs)
    return HTMLResponse(content=template.render(**context))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main viewer page"""
    # Add cache-busting version for app.js based on file modification time
    app_js_path = frontend_path / "app.js"
    if app_js_path.exists():
        version = int(app_js_path.stat().st_mtime)
    else:
        version = int(time.time())
    
    return template_response("index.html", request, app_js_version=version)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002, reload=True)

