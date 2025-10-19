"""
API клиент для работы с Raspyx API
Управляет аутентификацией и предоставляет базовые методы для запросов
"""
import httpx
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from config import settings


class RaspyxAPIClient:
    """Клиент для работы с Raspyx API с автоматической авторизацией"""
    
    def __init__(self, base_url: str = "https://zefixed.ru/raspyx"):
        """
        Инициализация API клиента
        
        Args:
            base_url: Базовый URL API
        """
        self.base_url = base_url
        self.jwt_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None
    
    async def authenticate(self) -> bool:
        """
        Авторизация в API и получение JWT токена
        
        Returns:
            True если авторизация успешна
        """
        if not settings.api_username or not settings.api_password:
            logger.warning("API credentials not configured")
            return False
        
        url = f"{self.base_url}/api/v1/users/login"
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                data = {
                    "username": settings.api_username,
                    "password": settings.api_password
                }
                
                response = await client.post(url, json=data)
                response.raise_for_status()
                
                result = response.json()
                
                # Получаем токен из ответа
                if result.get("status") == "OK" and "response" in result:
                    token_data = result["response"]
                    # Предполагаем что токен возвращается в поле token или access_token
                    self.jwt_token = token_data.get("token") or token_data.get("access_token")
                    
                    if self.jwt_token:
                        # Устанавливаем срок действия токена (обычно 24 часа)
                        self.token_expires_at = datetime.now() + timedelta(hours=23)
                        logger.info("Successfully authenticated with Raspyx API")
                        return True
                
                logger.error("Invalid response format during authentication")
                return False
                
        except httpx.HTTPStatusError as e:
            logger.error(f"Authentication failed: HTTP {e.response.status_code}")
            return False
        except httpx.TimeoutException:
            logger.error("Authentication timeout")
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False
    
    async def ensure_authenticated(self) -> bool:
        """
        Проверить и обновить токен при необходимости
        
        Returns:
            True если токен действителен
        """
        # Проверяем есть ли токен и не истек ли он
        if self.jwt_token and self.token_expires_at:
            if datetime.now() < self.token_expires_at:
                return True
        
        # Токена нет или он истек - авторизуемся заново
        return await self.authenticate()
    
    def get_auth_headers(self) -> Dict[str, str]:
        """
        Получить заголовки авторизации
        
        Returns:
            Словарь с заголовками
        """
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        
        return headers
    
    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        retry_auth: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить HTTP запрос к API с автоматической авторизацией
        
        Args:
            method: HTTP метод (GET, POST, PUT, DELETE)
            endpoint: Endpoint API (без базового URL)
            params: Query параметры
            json_data: JSON данные для POST/PUT запросов
            retry_auth: Повторить запрос после авторизации при 401
            
        Returns:
            Данные ответа или None
        """
        # Убедимся что авторизованы
        if not await self.ensure_authenticated():
            logger.error("Failed to authenticate before request")
            return None
        
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = self.get_auth_headers()
                
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data
                )
                
                elapsed_time = time.time() - start_time
                logger.info(f"API {method} {endpoint} - {response.status_code} ({elapsed_time:.2f}s)")
                
                response.raise_for_status()
                
                result = response.json()
                
                # Проверяем формат ответа согласно спецификации
                if result.get("status") == "OK" and "response" in result:
                    return result["response"]
                
                logger.error(f"Invalid response format from {endpoint}")
                return None
                
        except httpx.HTTPStatusError as e:
            elapsed_time = time.time() - start_time
            
            if e.response.status_code == 401 and retry_auth:
                logger.warning(f"API 401 {endpoint} - re-authenticating")
                # Пытаемся авторизоваться и повторить запрос
                if await self.authenticate():
                    return await self.request(
                        method, endpoint, params, json_data, retry_auth=False
                    )
            elif e.response.status_code == 404:
                logger.warning(f"API 404 {endpoint}")
            else:
                logger.error(f"API {e.response.status_code} {endpoint} ({elapsed_time:.2f}s)")
            return None
        except httpx.TimeoutException:
            elapsed_time = time.time() - start_time
            logger.error(f"API timeout {endpoint} ({elapsed_time:.2f}s)")
            return None
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"API error {endpoint}: {e} ({elapsed_time:.2f}s)")
            return None
    
    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить GET запрос
        
        Args:
            endpoint: Endpoint API
            params: Query параметры
            
        Returns:
            Данные ответа или None
        """
        return await self.request("GET", endpoint, params=params)
    
    async def post(
        self,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить POST запрос
        
        Args:
            endpoint: Endpoint API
            json_data: JSON данные
            
        Returns:
            Данные ответа или None
        """
        return await self.request("POST", endpoint, json_data=json_data)
    
    async def put(
        self,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить PUT запрос
        
        Args:
            endpoint: Endpoint API
            json_data: JSON данные
            
        Returns:
            Данные ответа или None
        """
        return await self.request("PUT", endpoint, json_data=json_data)
    
    async def delete(
        self,
        endpoint: str
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить DELETE запрос
        
        Args:
            endpoint: Endpoint API
            
        Returns:
            Данные ответа или None
        """
        return await self.request("DELETE", endpoint)


# Глобальный экземпляр API клиента
api_client = RaspyxAPIClient()

