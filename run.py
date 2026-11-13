import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Never enable the debugger on a publicly forwarded port (Codespaces): it allows code execution.
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
