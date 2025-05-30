from flask import Flask, request, jsonify
import requests
import json
import time
import os
import threading
import re
from datetime import datetime

app = Flask(__name__)

# 配置信息
BOT_TOKEN = "xxx"
API_BASE_URL = "https://chat-go.jwzhd.com/open-apis/v1/bot"
SEND_API_URL = f"{API_BASE_URL}/send?token={BOT_TOKEN}"
STREAM_API_URL = f"{API_BASE_URL}/send-stream?token={BOT_TOKEN}"
RECALL_API_URL = f"{API_BASE_URL}/recall?token={BOT_TOKEN}"
EDIT_API_URL = f"{API_BASE_URL}/edit?token={BOT_TOKEN}"
MESSAGES_API_URL = f"{API_BASE_URL}/messages?token={BOT_TOKEN}"

# 存储消息历史（实际应用中应使用数据库）
message_history = {}

@app.route('/webhook', methods=['POST'])
def webhook():
    """接收事件订阅消息的主入口"""
    try:
        data = request.json
        app.logger.info(f"收到事件: {json.dumps(data, indent=2)}")
        
        # 验证事件格式
        if 'header' not in data or 'event' not in data:
            return jsonify({"code": 1002, "msg": "invalid event format"}), 400
        
        event_type = data['header']['eventType']
        
        # 根据事件类型路由到不同处理器
        handlers = {
            'message.receive.normal': handle_normal_message,
            'message.receive.instruction': handle_instruction,
            'bot.followed': handle_follow,
            'bot.unfollowed': handle_unfollow,
            'group.join': handle_group_join,
            'group.leave': handle_group_leave,
            'button.report.inline': handle_button_click,
            'bot.shortcut.menu': handle_shortcut_menu,
        }
        
        handler = handlers.get(event_type, handle_unknown_event)
        return handler(data)
    except Exception as e:
        app.logger.error(f"处理事件时出错: {str(e)}")
        return jsonify({"code": 1002, "msg": "server error"}), 500

def handle_normal_message(data):
    """处理普通消息"""
    event = data['event']
    message = event['message']
    sender = event['sender']
    chat = event['chat']
    
    # 存储消息历史
    store_message_history(chat['chatId'], message)
    
    # 获取消息内容（根据不同的contentType处理）
    content_type = message.get('contentType')
    content_text = ""
    
    if content_type == 'text':
        content_text = message['content']['text']
    elif content_type == 'markdown':
        content_text = message['content']['text']
    else:
        # 非文本消息暂不处理
        return jsonify({"code": 1, "msg": "ignored"})
    
    # 命令处理
    if content_text.startswith("/"):
        return handle_command(content_text, chat, sender)
    
    # 智能回复
    return handle_smart_reply(content_text, chat, sender)

def handle_command(command, chat, sender):
    """处理用户命令"""
    command = command.lower().strip()
    
    if command == "/help":
        help_text = (
            "🤖 机器人命令帮助:\n"
            "-----------------\n"
            "/help - 显示帮助信息\n"
            "/time - 显示当前时间\n"
            "/calc [表达式] - 计算数学表达式\n"
            "/history - 查看聊天历史\n"
            "/weather [城市] - 查询天气(示例)\n"
            "/stream - 测试流式消息\n"
            "/recall - 撤回上一条消息\n"
        )
        return send_message(help_text, chat['chatId'], chat['chatType'])
    
    elif command == "/time":
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return send_message(f"🕒 当前时间: {current_time}", chat['chatId'], chat['chatType'])
    
    elif command.startswith("/calc"):
        expr = command[5:].strip()
        if not expr:
            return send_message("请输入要计算的表达式，例如: /calc 3+5*2", chat['chatId'], chat['chatType'])
        
        try:
            # 安全计算 - 只允许基本数学运算
            if not re.match(r'^[\d\s+\-*/().]+$', expr):
                return send_message("❌ 表达式包含不安全字符", chat['chatId'], chat['chatType'])
            
            result = eval(expr)
            reply = f"🧮 计算结果: {expr} = {result}"
            return send_message(reply, chat['chatId'], chat['chatType'])
        except Exception as e:
            return send_message(f"❌ 计算失败: {str(e)}", chat['chatId'], chat['chatType'])
    
    elif command == "/history":
        history = get_message_history(chat['chatId'])
        if not history:
            return send_message("📜 暂无聊天历史", chat['chatId'], chat['chatType'])
        
        # 只显示最近的5条消息
        history_text = "📜 最近聊天记录:\n-----------------\n"
        for msg in history[-5:]:
            time_str = datetime.fromtimestamp(msg['sendTime']/1000).strftime("%H:%M")
            history_text += f"{time_str} {msg['senderNickname']}: {msg['content']['text']}\n"
        
        return send_message(history_text, chat['chatId'], chat['chatType'])
    
    elif command == "/stream":
        # 启动新线程发送流式消息
        threading.Thread(target=send_stream_message, 
                         args=("正在传输流式消息...", chat['chatId'], chat['chatType'])).start()
        return jsonify({"code": 1, "msg": "processing"})
    
    elif command == "/recall":
        # 撤回最后一条消息
        last_msg = get_last_message(chat['chatId'])
        if last_msg:
            recall_message(last_msg['msgId'], chat['chatId'], chat['chatType'])
            return send_message("已撤回上一条消息", chat['chatId'], chat['chatType'])
        else:
            return send_message("没有可撤回的消息", chat['chatId'], chat['chatType'])
    
    else:
        return send_message(f"❌ 未知命令: {command}\n输入 /help 查看帮助", chat['chatId'], chat['chatType'])

def handle_smart_reply(text, chat, sender):
    """智能回复用户消息"""
    text = text.lower()
    
    # 问候语处理
    greetings = ["你好", "hello", "hi", "嗨", "在吗"]
    if any(g in text for g in greetings):
        reply = f"👋 你好 {sender['senderNickname']}！我是智能助手，有什么可以帮您？"
        return send_message(reply, chat['chatId'], chat['chatType'])
    
    # 感谢处理
    if "谢谢" in text or "感谢" in text:
        return send_message("不客气，很高兴能帮到您！😊", chat['chatId'], chat['chatType'])
    
    # 默认回复
    return send_message("收到您的消息了！输入 /help 查看可用命令", chat['chatId'], chat['chatType'])

def handle_instruction(data):
    """处理指令消息"""
    event = data['event']
    message = event['message']
    chat = event['chat']
    
    command_id = message.get('commandId')
    command_name = message.get('commandName')
    
    # 根据指令ID或名称执行操作
    if command_name == "时间":
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return send_message(f"🕒 当前时间: {current_time}", chat['chatId'], chat['chatType'])
    
    return jsonify({"code": 1, "msg": "success"})

def handle_button_click(data):
    """处理按钮点击事件"""
    button_value = data['value']
    user_id = data['userId']
    
    # 根据按钮值执行操作
    if button_value == "confirm":
        return send_message("✅ 操作已确认！", user_id, "user")
    elif button_value == "cancel":
        return send_message("❌ 操作已取消", user_id, "user")
    
    return jsonify({"code": 1, "msg": "success"})

def handle_follow(data):
    """处理关注事件"""
    event = data['event']
    sender = event['sender']
    
    # 发送欢迎消息
    welcome_msg = (
        "🎉 感谢关注！我是智能助手\n"
        "输入 /help 查看可用命令\n"
        "有什么可以帮您的？"
    )
    return send_message(welcome_msg, sender['senderId'], sender['senderType'])

def handle_unfollow(data):
    """处理取关事件"""
    # 记录日志即可，无法再发送消息
    app.logger.info(f"用户取关: {data}")
    return jsonify({"code": 1, "msg": "success"})

def handle_group_join(data):
    """处理入群事件"""
    event = data['event']
    chat = event['chat']
    sender = event['sender']
    
    # 发送群欢迎消息
    welcome_msg = (
        f"👋 欢迎 {sender['senderNickname']} 加入群聊！\n"
        "我是本群的智能助手，输入 /help 查看可用命令"
    )
    return send_message(welcome_msg, chat['chatId'], chat['chatType'])

def handle_group_leave(data):
    """处理退群事件"""
    # 记录日志
    app.logger.info(f"用户退群: {data}")
    return jsonify({"code": 1, "msg": "success"})

def handle_shortcut_menu(data):
    """处理快捷菜单事件"""
    event = data['event']
    sender = event['sender']
    
    # 发送快捷菜单帮助
    help_text = (
        "📱 快捷菜单功能:\n"
        "----------------\n"
        "1. 查询时间 - /time\n"
        "2. 计算器 - /calc\n"
        "3. 帮助信息 - /help"
    )
    return send_message(help_text, sender['senderId'], sender['senderType'])

def handle_unknown_event(data):
    """处理未知事件"""
    app.logger.warning(f"未知事件类型: {data['header']['eventType']}")
    return jsonify({"code": 1, "msg": "unknown event"})

def store_message_history(chat_id, message):
    """存储消息历史"""
    if chat_id not in message_history:
        message_history[chat_id] = []
    
    # 只存储文本消息
    if message.get('contentType') in ['text', 'markdown']:
        # 添加发送者信息
        message['senderNickname'] = message.get('senderNickname', '未知用户')
        message_history[chat_id].append(message)
        
        # 限制历史记录长度
        if len(message_history[chat_id]) > 50:
            message_history[chat_id] = message_history[chat_id][-50:]

def get_message_history(chat_id):
    """获取消息历史"""
    return message_history.get(chat_id, [])

def get_last_message(chat_id):
    """获取最后一条消息"""
    history = get_message_history(chat_id)
    return history[-1] if history else None

def send_message(text, recv_id, recv_type, buttons=None):
    """发送普通消息"""
    payload = {
        "recvId": recv_id,
        "recvType": recv_type,
        "contentType": "text",
        "content": {"text": text}
    }
    
    # 添加按钮
    if buttons:
        payload['content']['buttons'] = buttons
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(SEND_API_URL, headers=headers, json=payload)
        result = response.json()
        
        # 存储机器人发送的消息
        if result.get('code') == 1 and 'data' in result:
            msg_info = result['data']['messageInfo']
            store_message_history(recv_id, {
                "msgId": msg_info['msgId'],
                "contentType": "text",
                "content": {"text": text},
                "sendTime": int(time.time() * 1000),
                "senderNickname": "机器人"
            })
        
        return result
    except Exception as e:
        app.logger.error(f"消息发送失败: {str(e)}")
        return {"code": 100, "msg": str(e)}

def send_stream_message(text, recv_id, recv_type):
    """发送流式消息"""
    url = f"{STREAM_API_URL}&recvId={recv_id}&recvType={recv_type}&contentType=text"
    headers = {
        'Transfer-Encoding': 'chunked',
        'Content-Type': 'text/plain'
    }
    
    try:
        # 分块发送消息
        def generate_chunks():
            for i, char in enumerate(text):
                # 每5个字符作为一个块
                if i % 5 == 0:
                    chunk = text[i:i+5]
                    yield f"{len(chunk)}\r\n{chunk}\r\n".encode()
                    time.sleep(0.3)  # 模拟延迟
            yield b"0\r\n\r\n"  # 结束块
        
        # 创建请求并发送
        response = requests.post(url, headers=headers, data=generate_chunks())
        return response.json()
    except Exception as e:
        app.logger.error(f"流式消息发送失败: {str(e)}")
        return {"code": 100, "msg": str(e)}

def recall_message(msg_id, chat_id, chat_type):
    """撤回消息"""
    payload = {
        "msgId": msg_id,
        "chatId": chat_id,
        "chatType": chat_type
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(RECALL_API_URL, headers=headers, json=payload)
        return response.json()
    except Exception as e:
        app.logger.error(f"消息撤回失败: {str(e)}")
        return {"code": 100, "msg": str(e)}

def edit_message(msg_id, recv_id, recv_type, new_content):
    """编辑消息"""
    payload = {
        "msgId": msg_id,
        "recvId": recv_id,
        "recvType": recv_type,
        "contentType": "text",
        "content": {"text": new_content}
    }
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(EDIT_API_URL, headers=headers, json=payload)
        return response.json()
    except Exception as e:
        app.logger.error(f"消息编辑失败: {str(e)}")
        return {"code": 100, "msg": str(e)}

def get_messages(chat_id, chat_type, message_id=None, before=0, after=0):
    """获取消息列表"""
    params = {
        "chat-id": chat_id,
        "chat-type": chat_type,
    }
    
    if message_id:
        params["message-id"] = message_id
    
    if before > 0:
        params["before"] = before
    
    if after > 0:
        params["after"] = after
    
    try:
        response = requests.get(MESSAGES_API_URL, params=params)
        return response.json()
    except Exception as e:
        app.logger.error(f"获取消息列表失败: {str(e)}")
        return {"code": 100, "msg": str(e)}

if __name__ == '__main__':
    # 启动服务器
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
