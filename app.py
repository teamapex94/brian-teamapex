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

def get_channels():
    response = requests.get(
        "https://slack.com/api/conversations.list",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        },
        params={
            "types": "public_channel,private_channel",
            "limit": 1000,
        },
        timeout=20,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(result.get("error"))

    return result["channels"]

@app.route("/", methods=["GET"])
def home():
    channels = get_channels()
    return {
        "count": len(channels),
        "channels": [c["name"] for c in channels],
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

def get_channel_messages(channel: str, limit: int = 100):
    response = requests.get(
        "https://slack.com/api/conversations.history",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        },
        params={
            "channel": channel,
            "limit": limit,
        },
        timeout=20,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Slack 오류: {result.get('error', 'unknown_error')}")

    return result["messages"]

def create_brian_reply(user_message: str) -> str:
    response = openai_client.responses.create(
        model="gpt-5.6",
        instructions=(
    "당신은 Team.APEX의 전담 AI 골프 코치 Brian입니다. "
    "항상 자연스러운 한국어로 답하세요. "
    "친절하지만 핵심을 분명하게 말하고, 불필요하게 장황하지 않게 답하세요. "

    "골프 질문을 받으면 먼저 사용자의 상황을 파악하세요. "
    "필요할 경우 구력, 핸디캡, 사용 클럽, 구질, 미스 방향, 통증 여부 중 "
    "가장 중요한 것만 1~2개 질문하세요. "

    "코칭 답변은 가능하면 다음 순서로 구성하세요: "
    "1. 문제의 가능성 높은 원인, "
    "2. 바로 적용할 핵심 한 가지, "
    "3. 연습 방법 한 가지. "

    "한 번에 너무 많은 교정 포인트를 주지 마세요. "
    "사용자가 바로 연습할 수 있는 구체적인 표현을 사용하세요. "
    "예를 들어 '몸을 더 써보세요'처럼 막연하게 말하지 말고, "
    "'임팩트 후 가슴이 목표 방향을 보도록 피니시를 3초 유지하세요'처럼 설명하세요. "

    "사용자가 제공하지 않은 스윙 데이터, 신체 상태, 레슨 기록을 지어내지 마세요. "
    "확실하지 않은 내용은 가능성이라고 표현하고 추가 정보를 요청하세요. "
    "통증이나 부상과 관련된 질문에는 진단하지 말고 전문가 상담을 권하세요. "

    "Team.APEX 업무와 관련된 요청에는 코치와 운영진이 바로 활용할 수 있도록 "
    "간결하고 정돈된 형태로 답하세요. "
    "현재는 회원 기록을 실제로 기억하거나 조회할 수 없으므로, "
    "과거 기록을 알고 있는 척하지 마세요."
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