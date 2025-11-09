import asyncio
import aiohttp
from datetime import datetime
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register(
    "easylive", 
    "Dayanshifu", 
    "bilibili直播间推送", 
    "1.0",
    "https://github.com/Dayanshifu/astrbot_plugin_bilibili_livereminder"
)
class BilibiliLiveMonitor(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        
        self.room_configs = self.get_config("room_configs", "7857879:1044727986")
        self.check_interval = self.get_config("check_interval", 60)  # 检查间隔(秒)
        
        # 解析配置
        self.monitor_rooms = self.parse_room_configs()
        
        # 初始化状态跟踪
        self.room_status = {}  # 房间状态跟踪
        self.anchor_names = {}  # 主播昵称缓存
        
        self.session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://live.bilibili.com"
        })
        
        asyncio.create_task(self.monitor_task())

    def parse_room_configs(self):
        """解析房间配置字符串"""
        rooms = []
        configs = self.room_configs.split(',')
        for config in configs:
            if ':' in config:
                room_id, group_id = config.split(':', 1)
                rooms.append({
                    'room_id': room_id.strip(),
                    'group_id': group_id.strip()
                })
            else:
                # 如果没有指定群号，使用默认配置或记录错误
                logger.warning(f"无效的配置格式: {config}")
        return rooms

    async def get_anchor_info(self, room_id):
        """获取主播昵称信息"""
        try:
            room_url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
            async with self.session.get(room_url, timeout=5) as resp:
                room_data = await resp.json()
                if room_data['code'] == 0:
                    anchor_name = room_data['data']['anchor']['uname']
                    self.anchor_names[room_id] = anchor_name
                    return anchor_name
        except Exception as e:
            logger.error(f"获取房间 {room_id} 主播信息失败: {str(e)}")
        
        # 如果获取失败，使用默认名称
        return f"主播{room_id}"

    async def check_live_status(self, room_id):
        """检查单个直播间的状态"""
        try:
            url = f"链接2{room_id}"
            async with self.session.get(url, timeout=10) as resp:
                data = await resp.json()
                if data.get('code') == 0:
                    return {
                        'room_id': room_id,
                        'data': data['data'],
                        'timestamp': datetime.now()
                    }
        except Exception as e:
            logger.error(f"检查直播间 {room_id} 状态失败: {str(e)}")
        return None

    async def monitor_task(self):
        """监控任务主循环"""
        while True:
            try:
                # 并行检查所有直播间
                tasks = [self.check_live_status(room['room_id']) for room in self.monitor_rooms]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"检查直播间 {self.monitor_rooms[i]['room_id']} 时出错: {str(result)}")
                        continue
                    
                    if result is None:
                        continue
                    
                    room_id = result['room_id']
                    data = result['data']
                    current_status = data['live_status']
                    
                    # 初始化房间状态
                    if room_id not in self.room_status:
                        self.room_status[room_id] = {
                            'last_status': None,
                            'live_start_time': None,
                            'last_check_time': None
                        }
                    
                    room_info = self.room_status[room_id]
                    
                    # 首次检查，只记录状态
                    if room_info['last_status'] is None:
                        room_info['last_status'] = current_status
                        if current_status == 1:
                            room_info['live_start_time'] = datetime.fromtimestamp(data['live_time'])
                        logger.info(f"直播间 {room_id} 初始状态: {'开播' if current_status == 1 else '下播'}")
                    
                    # 状态发生变化
                    elif current_status != room_info['last_status']:
                        # 获取主播昵称
                        anchor_name = await self.get_anchor_info(room_id)
                        
                        message = ""
                        if current_status == 1:
                            room_info['live_start_time'] = datetime.fromtimestamp(data['live_time'])
                            message = f"{anchor_name} 开播了！\n传送门：https://live.bilibili.com/{room_id}"
                        else:
                            room_info['live_start_time'] = None
                            message = f"{anchor_name} 的直播已结束。"
                        
                        room_info['last_status'] = current_status
                        
                        # 发送通知到对应的群
                        target_group = None
                        for room_config in self.monitor_rooms:
                            if room_config['room_id'] == room_id:
                                target_group = room_config['group_id']
                                break
                        
                        if target_group:
                            # 存储通知消息，在收到群消息时发送
                            if 'notifications' not in self.room_status[room_id]:
                                self.room_status[room_id]['notifications'] = []
                            self.room_status[room_id]['notifications'].append({
                                'message': message,
                                'group_id': target_group
                            })
                        
                        logger.info(f"直播间 {room_id} 状态变化: {message}")
                    
                    room_info['last_check_time'] = result['timestamp']
                
            except Exception as e:
                logger.error(f"监控任务出错: {str(e)}")
            
            await asyncio.sleep(self.check_interval)

    async def get_live_info(self, room_id):
        """获取单个直播间的详细信息"""
        result = await self.check_live_status(room_id)
        if result is None:
            return f"直播间 {room_id}：无法获取直播信息"
        
        data = result['data']
        anchor_name = self.anchor_names.get(room_id, f"主播{room_id}")
        
        status_text = "直播中" if data['live_status'] == 1 else "未开播"
        info = f"主播: {anchor_name}\n直播间ID: {room_id}\n状态: {status_text}\n"
        
        if data['live_status'] == 1:
            room_info = self.room_status.get(room_id, {})
            if room_info.get('live_start_time'):
                duration = datetime.now() - room_info['live_start_time']
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                info += f"开播时间: {room_info['live_start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                info += f"直播时长: {int(hours)}小时{int(minutes)}分钟{int(seconds)}秒\n"
            else:
                info += "开播时间: 未知\n"
        
        room_info = self.room_status.get(room_id, {})
        if room_info.get('last_check_time'):
            info += f"最后检查时间: {room_info['last_check_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        info += f"直播间链接: 链接1{room_id}"
        
        return info

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id())
        message_str = event.message_str.strip().lower()
        
        # 检查是否有该群的通知消息
        notifications_to_send = []
        for room_id, room_info in self.room_status.items():
            if 'notifications' in room_info:
                for notification in room_info['notifications'][:]:
                    if notification['group_id'] == group_id:
                        notifications_to_send.append(notification['message'])
                        room_info['notifications'].remove(notification)
        
        # 发送积压的通知消息
        for notification in notifications_to_send:
            yield event.plain_result(notification)
        
        # 处理 liveinfo 命令
        if message_str == "liveinfo":
            info_lines = []
            for room_config in self.monitor_rooms:
                if room_config['group_id'] == group_id:
                    room_info = await self.get_live_info(room_config['room_id'])
                    info_lines.append(room_info)
            
            if info_lines:
                response = "直播间状态\n" + "\n" + "="*20 + "\n".join(info_lines)
                yield event.plain_result(response)
            else:
                yield event.plain_result("该群没有配置监控的直播间")

    async def terminate(self):
        """清理资源"""
        try:
            await self.session.close()
        except:
            pass
        logger.info("BilibiliLiveMonitor 插件已停止")