from flask import Flask, request, jsonify
app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return {
        "status": "ok",
        "service": "Brian | Team.APEX"
    }


@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json(silent=True) or {}

    # Slack URL 인증
    if data.get("type") == "url_verification":
        return jsonify({
            "challenge": data.get("challenge")
        })

    # 나중에 Slack 메시지를 처리할 위치
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
