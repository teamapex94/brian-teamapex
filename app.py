import hashlib
import hmac
import os
import re
import threading
import time

import requests
from flask import Flask, jsonify, request
from openai import OpenAI


app = Flask(__name__)

openai_client = OpenAI()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")


@app.route("/", methods=["GET"])
def home():
    return {
        "status": "ok",
        "service": "Brian | Team.APEX"
    }


def verify_slack_request() -> bool:
    """Slack에서 실제로 보낸 요청인지 확인합니다."""
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    slack_signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp or not slack_signature:
        return False

    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False

    request_body = request.get_data(as_text=True)
    base_string = f"v0:{timestamp}:{request_body}"

    calculated_signature = (
        "v0="
        + hmac.new(
            SLACK_SIGNING_SECRET.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    )

    return hmac.compare_digest(calculated_signature, slack_signature)


def remove_brian_mention(text: str) -> str:
    """메시지에서 <@봇ID> 형태의 멘션을 제거합니다."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def send_slack_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    payload = {
        "channel": channel,
        "text": text,
    }

    if thread_ts:
        payload["thread_ts"] = thread_ts

    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Slack 오류: {result.get('error', 'unknown_error')}")


def create_brian_reply(user_message: str) -> str:
    response = openai_client.responses.create(
        model="gpt-5.6",
        instructions=(
            "당신은 Team.APEX의 AI 골프 코치 Brian입니다. "
            "항상 한국어로 답하세요. 친절하고 전문적이되 장황하지 않게 답하세요. "
            "모르는 정보는 추측하지 말고 솔직하게 말하세요. "
            "현재는 일반적인 골프 코칭과 Team.APEX 업무 보조 역할을 수행합니다."
        ),
        input=user_message,
    )

    return response.output_text.strip()


def process_app_mention(event: dict) -> None:
    channel = event.get("channel")
    raw_text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not channel:
        return

    user_message = remove_brian_mention(raw_text)

    if not user_message:
        user_message = "인사해 주세요."

    try:
        brian_reply = create_brian_reply(user_message)
    except Exception as error:
        print(f"OpenAI 오류: {error}", flush=True)
        brian_reply = (
            "죄송합니다. 지금 AI 답변을 만드는 중 문제가 발생했습니다. "
            "잠시 후 다시 말씀해 주세요."
        )

    try:
        send_slack_message(channel, brian_reply, thread_ts)
    except Exception as error:
        print(f"Slack 전송 오류: {error}", flush=True)


@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json(silent=True) or {}

    # Slack URL 인증
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    if not verify_slack_request():
        return jsonify({"error": "invalid_signature"}), 401

    # Slack이 같은 이벤트를 재전송했을 때 중복 답변 방지
    if request.headers.get("X-Slack-Retry-Num"):
        return jsonify({"ok": True})

    event = data.get("event", {})

    if event.get("type") == "app_mention" and not event.get("bot_id"):
        threading.Thread(
            target=process_app_mention,
            args=(event,),
            daemon=True,
        ).start()

    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)