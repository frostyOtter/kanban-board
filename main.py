import asyncio

import httpx
import uvicorn

from kanban.api import app


async def send_mock_requests():
    base_url = "http://127.0.0.1:8000"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url}/tasks",
            json={
                "title": "Task 1",
                "description": "First mock task",
                "depends_on": [],
            },
        )
        print(f"Create Task 1: {response.status_code} - {response.json()}")

        response = await client.post(
            f"{base_url}/tasks",
            json={
                "title": "Task 2",
                "description": "Second mock task",
                "depends_on": [],
            },
        )
        print(f"Create Task 2: {response.status_code} - {response.json()}")
        task2_id = response.json()["id"]

        response = await client.get(f"{base_url}/tasks")
        print(f"List all tasks: {response.status_code} - {response.json()}")

        response = await client.post(f"{base_url}/tasks/{task2_id}/start")
        print(f"Start Task 2: {response.status_code} - {response.json()}")

        response = await client.post(f"{base_url}/tasks/{task2_id}/review")
        print(f"Review Task 2: {response.status_code} - {response.json()}")

        response = await client.post(f"{base_url}/tasks/{task2_id}/approve")
        print(f"Approve Task 2: {response.status_code} - {response.json()}")

        response = await client.get(f"{base_url}/board")
        print(f"Board snapshot: {response.status_code} - {response.json()}")


async def main():
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=8000,
            log_level="info",
        )
    )

    async def run_server():
        await server.serve()

    server_task = asyncio.create_task(run_server())

    await asyncio.sleep(2)

    await send_mock_requests()

    server.should_exit = True
    await server_task


if __name__ == "__main__":
    asyncio.run(main())
