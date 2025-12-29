import asyncio
import aiohttp
from datetime import datetime
from astrbot.api.event import MessageChain
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api import AstrBotConfig
import asyncio,os,requests

from astrbot.core.message.message_event_result import MessageChain
@register(
    "astrbot_plugin_bilibili_livemonitor", 
    "Dayanshifu", 
    "bilibili开播下播提醒", 
    "1.0.1",
    "https://github.com/Dayanshifu/astrbot_plugin_bilibili_livemonitor"
)
class BilibiliLiveMonitor(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.room_ids = []
        ids_list = config.get('ids', [])
        names_list = config.get('names', [])
        for i in range(min(len(ids_list), len(names_list))):
            self.room_ids.append((str(ids_list[i]), str(names_list[i])))
        
        self.target_groups = [str(g) for g in config.get('groups', [])]
        self.groups = []
        self.check_interval = config.get("time", 60)
        
        self.room_status = {
            room_id: {
                "last_status": None,
                "last_check_time": None,
                "live_start_time": None,
                "anchor_name": anchor_name
            } for room_id, anchor_name in self.room_ids
        }
        
        self.notifications = []
        self.session: aiohttp.ClientSession = None
        self.running = True

        asyncio.create_task(self.init_and_monitor())

    async def create_session(self):
        if self.session:
            try:
                if not self.session.closed:
                    await self.session.close()
            except Exception as e:
                logger.error(f"关闭旧会话失败: {str(e)}")
        self.session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://live.bilibili.com/"
        })

    async def get_room_init(self, room_id):
        try:
            if not self.session or self.session.closed:
                await self.create_session()
                
            url = f"https://api.live.bilibili.com/room/v1/Room/room_init?id={room_id}"
            async with self.session.get(url, timeout=10) as resp:
                data = await resp.json()
                if data.get('code') == 0:
                    return data['data']
        except Exception as e:
            logger.error(f"获取直播间{room_id}基础信息失败: {str(e)}")
        return None

    async def get_room_info(self, room_id):
        try:
            if not self.session or self.session.closed:
                await self.create_session()
                
            url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
            async with self.session.get(url, timeout=10) as resp:
                data = await resp.json()
                if data.get('code') == 0:
                    return data['data']
        except Exception as e:
            logger.error(f"获取直播间{room_id}详细信息失败: {str(e)}")
        return None

    async def check_live_status(self, room_id):
        try:
            init_data = await self.get_room_init(room_id)
            if not init_data:
                return None
            
            self.room_status[room_id]["last_check_time"] = datetime.now()
            room_data = await self.get_room_info(room_id)
            
            return {
                "live_status": init_data.get('live_status', 0),
                "room_id": room_id,
                "live_time": init_data.get('live_time'),
                "room_info": room_data,
                "anchor_name": self.room_status[room_id]["anchor_name"]
            }
        except Exception as e:
            logger.error(f"检查直播间{room_id}状态失败: {str(e)}")
        return None

    async def monitor_task(self):
        while self.running:
            try:
                for room_id, _ in self.room_ids:
                    status_data = await self.check_live_status(room_id)
                    if not status_data:
                        continue
                    
                    current_status = status_data['live_status']
                    last_status = self.room_status[room_id]["last_status"]
                    
                    if last_status is None:
                        self.room_status[room_id]["last_status"] = current_status
                        if current_status == 1:
                            try:
                                live_time = status_data['live_time']
                                self.room_status[room_id]["live_start_time"] = datetime.fromtimestamp(live_time)
                            except (ValueError, TypeError):
                                self.room_status[room_id]["live_start_time"] = datetime.now()
                        continue
                    
                    if current_status != last_status:
                        self.room_status[room_id]["last_status"] = current_status
                        
                        if current_status == 1:
                            room_info = status_data['room_info'] or {}
                            anchor_name = status_data['anchor_name']
                            room_title = room_info.get('title', '无标题')
                            room_url = f"https://live.bilibili.com/{room_id}"
                            cover_url = room_info.get('user_cover', '')
                            '''
                            message = [
                                Comp.Plain(f"{anchor_name} 开播了喵！\n{room_title}\n传送门: {room_url}")
                            ]
                            if cover_url:
                                message.append(Comp.Image.fromURL(cover_url))'''
                            save_dir = "covers"
                            new_name = f"{room_id}.jpg"
                            os.makedirs(save_dir, exist_ok=True)
                            response = requests.get(cover_url, headers={'User-Agent': 'Mozilla/5.0'})
                            response.raise_for_status()
                            save_path = os.path.join(save_dir, new_name)
                            with open(save_path, 'wb') as f:
                                f.write(response.content)
                            message=MessageChain().message(f"{anchor_name} 开播了喵！\n{room_title}\n传送门: {room_url}").file_image(save_path)
                            for group_id in self.groups:
                                await self.context.send_message(
                                    group_id,message
                                )
                                logger.info(f"已向群{group_id}发送通知")
                            logger.info(f"直播间{room_id}({anchor_name})开播")
                        else:
                            self.room_status[room_id]["live_start_time"] = None
                            anchor_name = self.room_status[room_id]["anchor_name"]
                            #self.notifications.append([
                            #    Comp.Plain(f"{anchor_name}的直播已结束喵。")
                            #])
                            message=MessageChain().message(f"{anchor_name}的直播已结束喵。")
                            for group_id in self.groups:
                                await self.context.send_message(
                                    group_id,message
                                )
                                logger.info(f"已向群{group_id}发送通知")
                            logger.info(f"直播间{room_id}({anchor_name})已下播")
            
            except Exception as e:
                logger.error(f"监控任务出错: {str(e)}")
            
            await asyncio.sleep(self.check_interval)


    async def get_live_info(self, room_id=None):
        room_id_list = [rid for rid, _ in self.room_ids]
        
        if room_id and room_id in room_id_list:
            status_data = await self.check_live_status(room_id)
            if not status_data:
                return f"直播间{room_id}（{self.room_status[room_id]['anchor_name']}）：无法获取直播信息，请稍后再试"
            
            room_info = status_data.get('room_info', {})
            anchor_name = status_data.get('anchor_name', '未知主播')
            status_text = "直播中" if status_data['live_status'] == 1 else "未开播"
            
            info = f"直播间ID: {room_id}\n"
            info += f"主播: {anchor_name}\n"
            info += f"状态: {status_text}\n"
            
            if status_data['live_status'] == 1 and self.room_status[room_id]["live_start_time"]:
                duration = datetime.now() - self.room_status[room_id]["live_start_time"]
                hours, remainder = divmod(duration.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                info += f"开播时间: {self.room_status[room_id]['live_start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                info += f"直播时长: {int(hours)}小时{int(minutes)}分钟{int(seconds)}秒\n"
            
            info += f"标题: {room_info.get('title', '无标题')}\n"
            if self.room_status[room_id]["last_check_time"]:
                info += f"最后检查时间: {self.room_status[room_id]['last_check_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
            info += f"直播间链接: https://live.bilibili.com/{room_id}"
            
            return info
        else:
            all_info = []
            for room_id, _ in self.room_ids:
                status_data = await self.check_live_status(room_id)
                if not status_data:
                    all_info.append(f"直播间{room_id}（{self.room_status[room_id]['anchor_name']}）：无法获取直播信息")
                    continue
                
                room_info = status_data.get('room_info', {})
                anchor_name = status_data.get('anchor_name', '未知主播')
                status_text = "直播中" if status_data['live_status'] == 1 else "未开播"
                
                info = f"直播间ID: {room_id}\n"
                info += f"主播: {anchor_name}\n"
                info += f"状态: {status_text}\n"
                
                if status_data['live_status'] == 1 and self.room_status[room_id]["live_start_time"]:
                    duration = datetime.now() - self.room_status[room_id]["live_start_time"]
                    hours, remainder = divmod(duration.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    info += f"开播时间: {self.room_status[room_id]['live_start_time'].strftime('%Y-%m-%d %H:%M:%S')}\n"
                    info += f"直播时长: {int(hours)}小时{int(minutes)}分钟{int(seconds)}秒\n"
            
                info += f"标题: {room_info.get('title', '无标题')}\n"
                info += f"直播间链接: https://live.bilibili.com/{room_id}\n"
                all_info.append(info)
            
            return "所有直播间状态\n\n" + chr(10).join(all_info)

    @filter.command("liveinfo")
    async def liveinfo_command(self, event: AstrMessageEvent, room_id: str = None):
        info = await self.get_live_info(room_id)
        yield event.plain_result(info)
    @filter.command("livedebug")
    async def livedebug_command(self, event: AstrMessageEvent, room_id: str = None):
        
        yield event.plain_result(1)
        for room_id, _ in self.room_ids:
            status_data = await self.check_live_status(room_id)
            if not status_data:
                continue
            
            current_status = status_data['live_status']
            last_status = self.room_status[room_id]["last_status"]
            
            if last_status is None:
                self.room_status[room_id]["last_status"] = current_status
                if current_status == 1:
                    try:
                        live_time = status_data['live_time']
                        self.room_status[room_id]["live_start_time"] = datetime.fromtimestamp(live_time)
                    except (ValueError, TypeError):
                        self.room_status[room_id]["live_start_time"] = datetime.now()
                continue
            self.room_status[room_id]["last_status"] = current_status
            room_info = status_data['room_info'] or {}
            anchor_name = status_data['anchor_name']
            room_title = room_info.get('title', '无标题')
            room_url = f"https://live.bilibili.com/{room_id}"
            cover_url = room_info.get('user_cover', '')
            '''
            message = [
                Comp.Plain(f"{anchor_name} 开播了喵！\n{room_title}\n传送门: {room_url}")
            ]
            if cover_url:
                message.append(Comp.Image.fromURL(cover_url))'''
            save_dir = "covers"
            new_name = f"{room_id}.jpg"
            os.makedirs(save_dir, exist_ok=True)
            response = requests.get(cover_url, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            save_path = os.path.join(save_dir, new_name)
            with open(save_path, 'wb') as f:
                f.write(response.content)
            message=MessageChain().message(f"{anchor_name} 开播了喵！\n{room_title}\n传送门: {room_url}").file_image(save_path)
            for group_id in self.groups:
                await self.context.send_message(
                    group_id,message
                )
                logger.info(f"已向群{group_id}发送通知")
            logger.info(f"直播间{room_id}({anchor_name})开播")
        
        await asyncio.sleep(self.check_interval)

    async def init_and_monitor(self):
        await self.create_session()
        await self.monitor_task()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        group_id = event.get_group_id()
        if  str(group_id) in self.target_groups:
            if str(group_id) not in self.groups:
                self.groups.append(event.unified_msg_origin)

            

    async def terminate(self):
        self.running = False
        try:
            if self.session and not self.session.closed:
                await self.session.close()
        except Exception as e:
            logger.error(f"关闭会话失败: {str(e)}")
        logger.info("直播间监控插件已停止")