from pathlib import Path
import pytest
from app.store import Delivery, MemoryStore


@pytest.mark.asyncio
async def test_cleanup_removes_expired_file():
    target = Path.cwd() / '.test-expired-movie.mp4'
    target.write_bytes(b'video')
    try:
        store = MemoryStore(0)
        delivery = Delivery('delivery', file_path=target)
        store.deliveries[delivery.token] = delivery
        await store.cleanup()
        assert not store.deliveries
        assert not target.exists()
    finally:
        target.unlink(missing_ok=True)
