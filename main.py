from telethon import TelegramClient, sync
from telethon.tl.types import User, Chat, Channel
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
import asyncio
import logging
import os
import json
import sys
import time
from getpass import getpass
from concurrent.futures import ProcessPoolExecutor

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def get_credentials():
    print("Please enter your Telegram API credentials.")
    api_id = input("API ID: ")
    api_hash = input("API Hash: ")
    try:
        with open(config_path, 'w') as f:
            json.dump({'api_id': api_id, 'api_hash': api_hash}, f)
    except Exception as e:
        logger.error(f"Error saving config file: {e}")
    return api_id, api_hash

async def delete_dm_completely(client, entity, index, total):
    name = f"{entity.first_name} {getattr(entity, 'last_name', '')}"
    print(f"[{index}/{total}] ⏳ Processing DM with: {name}")
    start_time = time.time()
    try:
        await asyncio.gather(
            client(DeleteHistoryRequest(peer=entity, max_id=0, just_clear=False, revoke=True)),
            client.delete_dialog(entity, revoke=True)
        )
        try:
            await client.send_message(entity, "/delete")
            messages = await client.get_messages(entity, limit=100)
            if messages:
                message_ids = [msg.id for msg in messages]
                await client.delete_messages(entity, message_ids, revoke=True)
        except Exception:
            pass
        elapsed = time.time() - start_time
        print(f"[{index}/{total}] ✅ Deleted DM with {name} in {elapsed:.2f}s")
        return True
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{index}/{total}] ❌ Failed to delete DM with {name}: {e} ({elapsed:.2f}s)")
        return False

async def leave_group_completely(client, entity, index, total):
    title = getattr(entity, 'title', 'Unknown')
    entity_type = "Supergroup" if isinstance(entity, Channel) and entity.megagroup else \
                 "Channel" if isinstance(entity, Channel) else "Group"
    
    print(f"[{index}/{total}] ⏳ Leaving {entity_type}: {title}")
    start_time = time.time()
    try:
        if isinstance(entity, Chat):
            await client.delete_dialog(entity)
        elif isinstance(entity, Channel):
            await client(LeaveChannelRequest(entity))
            await client.delete_dialog(entity)
        elapsed = time.time() - start_time
        print(f"[{index}/{total}] ✅ Left {entity_type}: {title} in {elapsed:.2f}s")
        return True, entity_type
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[{index}/{total}] ❌ Failed to leave {entity_type} {title}: {e} ({elapsed:.2f}s)")
        return False, entity_type

async def process_all_concurrently(client, dialogs):
    dm_dialogs = []
    group_dialogs = []
    print("\n🔍 Analyzing your dialogs...")
    for dialog in dialogs:
        entity = dialog.entity
        if isinstance(entity, User):
            dm_dialogs.append(entity)
        elif isinstance(entity, (Chat, Channel)):
            group_dialogs.append(entity)
    print(f"\n📊 Found {len(dm_dialogs)} DMs, {len(group_dialogs)} groups/channels to process")
    dm_count = 0
    group_count = 0
    channel_count = 0
    if dm_dialogs:
        print("\n🚀 PHASE 1: CLEANING DIRECT MESSAGES")
        dm_tasks = []
        batch_size = min(5, len(dm_dialogs))
        for i, entity in enumerate(dm_dialogs):
            task = asyncio.create_task(delete_dm_completely(client, entity, i+1, len(dm_dialogs)))
            dm_tasks.append(task)
            if len(dm_tasks) >= batch_size or i == len(dm_dialogs) - 1:
                results = await asyncio.gather(*dm_tasks, return_exceptions=True)
                dm_count += sum(1 for r in results if r is True)
                dm_tasks = []
                if i < len(dm_dialogs) - 1:
                    await asyncio.sleep(1)
    if group_dialogs:
        print("\n🚀 PHASE 2: LEAVING GROUPS AND CHANNELS")
        group_tasks = []
        batch_size = min(3, len(group_dialogs))
        for i, entity in enumerate(group_dialogs):
            task = asyncio.create_task(leave_group_completely(client, entity, i+1, len(group_dialogs)))
            group_tasks.append(task)
            if len(group_tasks) >= batch_size or i == len(group_dialogs) - 1:
                results = await asyncio.gather(*group_tasks, return_exceptions=True)
                for r in results:
                    if r and r[0]:
                        if r[1] == "Channel":
                            channel_count += 1
                        else:
                            group_count += 1
                group_tasks = []
                if i < len(group_dialogs) - 1:
                    await asyncio.sleep(1)
    return dm_count, group_count, channel_count

async def clean_telegram():
    total_start_time = time.time()
    print("\n🧹 TELEGRAM CLEANUP TOOL 🧹")
    print("----------------------------")
    api_id, api_hash = get_credentials()
    client = TelegramClient('tgclean_session', api_id, api_hash)
    try:
        print("\n📲 Connecting to Telegram...")
        await client.start()
        if not await client.is_user_authorized():
            print("⚠️ You need to log in first!")
            phone = input("Enter your phone number with country code: ")
            await client.send_code_request(phone)
            code = input("Enter the code you received: ")
            await client.sign_in(phone, code)
        print("✅ Logged in successfully!")
        print("\n📚 Fetching all conversations...")
        dialogs = await client.get_dialogs()
        print(f"📊 Found {len(dialogs)} total conversations")
        dm_count, group_count, channel_count = await process_all_concurrently(client, dialogs)
        total_time = time.time() - total_start_time
        print("\n🏁 CLEAN-UP SUMMARY 🏁")
        print("----------------------")
        print(f"✅ Deleted {dm_count} direct message conversations")
        print(f"✅ Left {group_count} groups/supergroups")
        print(f"✅ Left {channel_count} channels")
        print(f"⏱️ Total time: {total_time:.2f} seconds")
        print("----------------------")
    except Exception as e:
        logger.error(f"❌ An error occurred: {e}")
        raise
    finally:
        await client.disconnect()
        print("\n👋 Disconnected from Telegram")

if __name__ == '__main__':
    print("🚀 Starting Telegram clean-up...")
    if sys.version_info >= (3, 11):
        asyncio.run(clean_telegram())
    else:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(clean_telegram())
        finally:
            loop.close()
    print("\n✨ Clean-up completed! ✨")
