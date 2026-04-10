"""
AI API 客户端
支持自定义 URL 端点，兼容 OpenAI 接口格式
支持禁用思考模式以加速响应
"""
import json
import re
from typing import Optional

from openai import AsyncOpenAI
from loguru import logger


class GeminiClient:
    """
    AI API 客户端
    使用 OpenAI 兼容接口，支持自定义 base_url
    """

    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "gemini-2.0-flash")
        self.temperature = config.get("temperature", 0.3)
        self.max_tokens = config.get("max_tokens", 4096)
        self.disable_thinking = config.get("disable_thinking", True)

        # 使用 OpenAI 兼容客户端
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        logger.info(f"AI客户端初始化: model={self.model}, base_url={self.base_url}, disable_thinking={self.disable_thinking}")

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       max_tokens: Optional[int] = None) -> str:
        """
        调用 AI API 生成文本
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_tokens: 可选的最大token数（覆盖默认值）
            
        Returns:
            生成的文本内容
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 构建请求参数
        # kimi-k2.5 思考模式: temperature=1, 禁用思考: temperature=0.6
        effective_temp = self.temperature
        if self.disable_thinking and self.temperature == 1.0:
            effective_temp = 0.6

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": effective_temp,
            "max_tokens": max_tokens or self.max_tokens,
        }

        # 对思考模型禁用思考以加速响应
        if self.disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        try:
            response = await self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.debug(f"AI 生成完成，tokens: {response.usage.total_tokens if response.usage else 'N/A'}")
            return content

        except Exception as e:
            # 如果禁用思考失败，尝试不带思考参数重试
            if "thinking" in str(e).lower() or "disabled" in str(e).lower():
                logger.warning(f"禁用思考模式失败，尝试普通模式: {e}")
                kwargs.pop("extra_body", None)
                try:
                    response = await self._client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content
                    logger.debug(f"AI 生成完成（普通模式），tokens: {response.usage.total_tokens if response.usage else 'N/A'}")
                    return content
                except Exception as e2:
                    logger.error(f"AI API 调用失败（重试）: {e2}")
                    raise
            logger.error(f"AI API 调用失败: {e}")
            raise

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None,
                            max_tokens: Optional[int] = None) -> dict:
        """
        调用 AI API 并解析 JSON 响应
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            max_tokens: 可选的最大token数
            
        Returns:
            解析后的字典
        """
        response_text = await self.generate(prompt, system_prompt, max_tokens=max_tokens)
        
        # 尝试提取 JSON
        try:
            # 直接解析
            return json.loads(response_text)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块中提取
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            
            logger.warning(f"无法解析JSON响应: {response_text[:200]}...")
            return {"raw_response": response_text}

    async def close(self):
        """关闭客户端"""
        await self._client.close()

    def update_config(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                      model: Optional[str] = None):
        """动态更新配置"""
        if base_url:
            self.base_url = base_url
        if api_key:
            self.api_key = api_key
        if model:
            self.model = model
        
        # 重建客户端
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        logger.info(f"AI客户端配置更新: model={self.model}, base_url={self.base_url}")
