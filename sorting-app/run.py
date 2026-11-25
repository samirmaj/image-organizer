"""Start the app: python run.py  (scans the folder, then opens the browser)"""
import uvicorn

from app import server

if __name__ == "__main__":
    server.OPEN_BROWSER = True
    uvicorn.run(server.app, host="127.0.0.1", port=server.cfg["port"])
