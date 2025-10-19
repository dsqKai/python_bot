"""
HTTP сервер для экспорта метрик Prometheus
"""
import asyncio
from aiohttp import web
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from loguru import logger


async def metrics_handler(request):
    """Handler для /metrics endpoint"""
    metrics = generate_latest()
    # Разделяем content_type и charset, так как aiohttp не позволяет передавать charset в content_type
    content_type = CONTENT_TYPE_LATEST.split(';')[0]
    return web.Response(body=metrics, content_type=content_type, charset='utf-8')


async def health_handler(request):
    """Handler для /health endpoint"""
    return web.Response(text='OK', status=200)


class MetricsServer:
    """HTTP сервер для метрик"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8000):
        self.host = host
        self.port = port
        self.app = None
        self.runner = None
        self.site = None
    
    async def start(self):
        """Запуск сервера"""
        try:
            logger.info(f"Initializing metrics server on {self.host}:{self.port}...")
            self.app = web.Application()
            self.app.router.add_get('/metrics', metrics_handler)
            self.app.router.add_get('/health', health_handler)
            
            logger.info("Setting up AppRunner...")
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            logger.info("Starting TCPSite...")
            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            
            logger.info(f"Metrics server started on http://{self.host}:{self.port}/metrics")
            
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}", exc_info=True)
    
    async def stop(self):
        """Остановка сервера"""
        try:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()
            
            logger.info("Metrics server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping metrics server: {e}")

