from flask import Flask

app = Flask(__name__)


@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "Brian | Team.APEX",
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)