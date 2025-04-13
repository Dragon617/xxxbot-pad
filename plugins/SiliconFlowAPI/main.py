import asyncio
import json
import os
import tomllib
import traceback
from typing import Dict, List, Optional, Union, Any
import uuid
import time
import threading

import aiohttp
from fastapi import FastAPI, Request, Response, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
from loguru import logger

from WechatAPI import WechatAPIClient
from database.XYBotDB import XYBotDB
from utils.decorators import *
from utils.plugin_base import PluginBase


class SiliconFlowAPI(PluginBase):
    description = "硅基流动 API 兼容插件"
    author = "XYBot团队"
    version = "1.0.0"
    is_ai_platform = True  # 标记为 AI 平台插件

    def __init__(self):
        super().__init__()

        try:
            # 读取主配置
            with open("main_config.toml", "rb") as f:
                main_config = tomllib.load(f)
            
            # 读取插件配置
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
                
            # 获取SiliconFlowAPI配置
            plugin_config = config.get("SiliconFlowAPI", {})
            self.enable = plugin_config.get("enable", False)
            self.api_key = plugin_config.get("api-key", "")
            self.base_url = plugin_config.get("base-url", "https://api.siliconflow.cn/v1")
            
            # 获取模型配置
            self.default_model = plugin_config.get("default-model", "Qwen/QwQ-32B")
            self.available_models = plugin_config.get("available-models", ["Qwen/QwQ-32B"])
            
            # 获取服务器配置
            self.port = plugin_config.get("port", 8200)
            self.host = plugin_config.get("host", "0.0.0.0")
            
            # 获取命令配置
            self.command_tip = plugin_config.get("command-tip", "")
            
            # 获取功能配置
            self.http_proxy = plugin_config.get("http-proxy", "")
            
            # 获取积分配置
            self.price = plugin_config.get("price", 0)
            self.admin_ignore = plugin_config.get("admin_ignore", True)
            self.whitelist_ignore = plugin_config.get("whitelist_ignore", True)
            
            # 获取高级设置
            self.max_tokens = plugin_config.get("max_tokens", 4096)
            self.temperature = plugin_config.get("temperature", 0.7)
            self.top_p = plugin_config.get("top_p", 0.7)
            self.top_k = plugin_config.get("top_k", 50)
            self.frequency_penalty = plugin_config.get("frequency_penalty", 0.5)
            
            # 初始化数据库
            self.db = XYBotDB()
            
            # 获取管理员列表
            self.admins = main_config.get("XYBot", {}).get("admins", [])
            
            # 初始化FastAPI应用
            self.app = FastAPI(title="硅基流动 API 兼容服务", description="提供硅基流动 API 兼容的接口")
            
            # 添加CORS中间件
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            
            # 初始化服务器
            self.server = None
            self.server_thread = None
            
            # 设置API路由
            self._setup_routes()
            
            logger.success("SiliconFlowAPI插件初始化成功")
            
        except Exception as e:
            logger.error(f"SiliconFlowAPI插件初始化失败: {str(e)}")
            logger.error(traceback.format_exc())
            self.enable = False
    
    def _setup_routes(self):
        """设置API路由"""
        
        @self.app.get("/v1/models")
        async def list_models(request: Request):
            """列出可用的模型"""
            try:
                # 获取请求头中的API密钥
                api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
                
                # 如果配置了API密钥，验证请求中的API密钥
                if self.api_key and api_key != self.api_key:
                    # 如果API密钥不匹配，尝试转发到硅基流动API
                    return await self._forward_request(request, "/models")
                
                # 构建模型列表
                models = []
                for model_id in self.available_models:
                    models.append({
                        "id": model_id,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "organization-owner"
                    })
                
                return {
                    "object": "list",
                    "data": models
                }
            
            except Exception as e:
                logger.error(f"处理模型列表请求失败: {str(e)}")
                logger.error(traceback.format_exc())
                
                # 尝试转发到硅基流动API
                return await self._forward_request(request, "/models")
        
        @self.app.post("/v1/chat/completions")
        async def create_chat_completion(request: Request):
            """创建聊天完成"""
            try:
                # 获取请求体
                body = await request.json()
                
                # 获取请求头中的API密钥
                api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
                
                # 如果配置了API密钥，验证请求中的API密钥
                if self.api_key and api_key != self.api_key:
                    # 如果API密钥不匹配，尝试转发到硅基流动API
                    return await self._forward_request(request, "/chat/completions")
                
                # 应用默认参数（如果请求中没有指定）
                if "model" not in body:
                    body["model"] = self.default_model
                
                if "max_tokens" not in body and self.max_tokens > 0:
                    body["max_tokens"] = self.max_tokens
                
                if "temperature" not in body:
                    body["temperature"] = self.temperature
                
                if "top_p" not in body:
                    body["top_p"] = self.top_p
                
                if "top_k" not in body:
                    body["top_k"] = self.top_k
                
                if "frequency_penalty" not in body:
                    body["frequency_penalty"] = self.frequency_penalty
                
                # 转发请求到硅基流动API
                return await self._forward_request(request, "/chat/completions", body)
            
            except Exception as e:
                logger.error(f"处理聊天完成请求失败: {str(e)}")
                logger.error(traceback.format_exc())
                
                return JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "message": f"处理请求失败: {str(e)}",
                            "type": "server_error",
                            "code": "internal_server_error"
                        }
                    }
                )
        
        @self.app.get("/")
        async def root():
            """API根路径"""
            return {
                "message": "硅基流动 API 兼容服务已启动",
                "version": self.version,
                "models": self.available_models,
                "documentation": "/docs"
            }
        
        @self.app.get("/docs")
        async def get_docs():
            """API文档"""
            return {
                "message": "访问 /docs 查看API文档",
                "swagger_ui": "/docs",
                "redoc": "/redoc"
            }
    
    async def _forward_request(self, request: Request, path: str, modified_body: dict = None):
        """转发请求到硅基流动API"""
        try:
            # 构建请求头
            headers = dict(request.headers)
            
            # 如果配置了API密钥，使用配置的API密钥
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            # 设置内容类型
            headers["Content-Type"] = "application/json"
            
            # 移除主机头，避免冲突
            if "host" in headers:
                del headers["host"]
            
            # 设置代理
            proxy = self.http_proxy if self.http_proxy else None
            
            # 获取请求体
            if modified_body is not None:
                body = modified_body
            else:
                try:
                    body = await request.json()
                except:
                    body = None
            
            # 构建请求URL
            url = f"{self.base_url}{path}"
            
            # 发送请求
            async with aiohttp.ClientSession() as session:
                if request.method.upper() == "GET":
                    async with session.get(
                        url,
                        headers=headers,
                        proxy=proxy
                    ) as response:
                        # 获取响应
                        response_text = await response.text()
                        
                        # 尝试解析为JSON
                        try:
                            response_json = json.loads(response_text)
                            
                            # 返回响应
                            return Response(
                                content=json.dumps(response_json),
                                media_type="application/json",
                                status_code=response.status
                            )
                        except:
                            # 如果不是JSON，直接返回文本
                            return Response(
                                content=response_text,
                                media_type=response.headers.get("Content-Type", "text/plain"),
                                status_code=response.status
                            )
                
                elif request.method.upper() == "POST":
                    async with session.post(
                        url,
                        headers=headers,
                        json=body,
                        proxy=proxy
                    ) as response:
                        # 检查是否是流式响应
                        if response.headers.get("Content-Type") == "text/event-stream":
                            # 返回流式响应
                            return Response(
                                content=await response.read(),
                                media_type="text/event-stream",
                                status_code=response.status
                            )
                        
                        # 获取响应
                        response_text = await response.text()
                        
                        # 尝试解析为JSON
                        try:
                            response_json = json.loads(response_text)
                            
                            # 返回响应
                            return Response(
                                content=json.dumps(response_json),
                                media_type="application/json",
                                status_code=response.status
                            )
                        except:
                            # 如果不是JSON，直接返回文本
                            return Response(
                                content=response_text,
                                media_type=response.headers.get("Content-Type", "text/plain"),
                                status_code=response.status
                            )
                
                else:
                    # 不支持的方法
                    return JSONResponse(
                        status_code=405,
                        content={
                            "error": {
                                "message": f"不支持的方法: {request.method}",
                                "type": "method_not_allowed",
                                "code": "method_not_allowed"
                            }
                        }
                    )
        
        except Exception as e:
            logger.error(f"转发请求失败: {str(e)}")
            logger.error(traceback.format_exc())
            
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": f"转发请求失败: {str(e)}",
                        "type": "server_error",
                        "code": "internal_server_error"
                    }
                }
            )
    
    async def _start_server(self):
        """启动API服务器"""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info"
        )
        self.server = uvicorn.Server(config)
        await self.server.serve()
    
    def _run_server(self):
        """在线程中运行服务器"""
        asyncio.run(self._start_server())
    
    async def on_enable(self, bot=None):
        """插件启用时调用"""
        await super().on_enable(bot)
        
        if not self.enable:
            logger.warning("SiliconFlowAPI插件已禁用，不启动API服务器")
            return
        
        # 启动API服务器
        try:
            # 在新线程中启动服务器
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            
            logger.success(f"SiliconFlowAPI服务器已启动，监听地址: {self.host}:{self.port}")
            
            # 发送提示消息
            if bot and self.command_tip:
                # 向管理员发送提示
                for admin in self.admins:
                    try:
                        await bot.send_text_message(admin, self.command_tip)
                    except Exception as e:
                        logger.error(f"向管理员 {admin} 发送提示消息失败: {str(e)}")
        
        except Exception as e:
            logger.error(f"启动SiliconFlowAPI服务器失败: {str(e)}")
            logger.error(traceback.format_exc())
    
    async def on_disable(self):
        """插件禁用时调用"""
        # 停止API服务器
        if self.server:
            self.server.should_exit = True
            logger.info("SiliconFlowAPI服务器正在关闭...")
        
        await super().on_disable()
