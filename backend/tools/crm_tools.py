import argparse
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..integrations.crm.crm_sync_service import get_crm_sync_service, CRMSyncError
from ..integrations.crm.crm_interface import find_contact_by_email, upsert_contact_normalized, CRMIntegrationError

logger = logging.getLogger(__name__)


async def list_contacts(integration_name: str, query: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        # prefer list_contacts if implemented
        if hasattr(client, "list_contacts"):
            return await client.list_contacts(limit=limit)  # type: ignore
        # fallback to search_contacts
        if hasattr(client, "search_contacts"):
            resp = await client.search_contacts(query=(query or ""), limit=limit)  # type: ignore
            if isinstance(resp, dict):
                return resp.get("results") or resp.get("records") or resp.get("contacts") or []
            return list(resp)
        raise CRMSyncError("client does not support listing/searching contacts")
    except Exception as e:
        logger.exception("list_contacts failed for %s", integration_name)
        raise


async def get_contact(integration_name: str, contact_id: str) -> Optional[Dict[str, Any]]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        if hasattr(client, "get_contact"):
            return await client.get_contact(contact_id)  # type: ignore
        raise CRMSyncError("client does not support get_contact")
    except Exception as e:
        logger.exception("get_contact failed for %s id=%s", integration_name, contact_id)
        raise


async def create_contact(integration_name: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        if hasattr(client, "create_contact"):
            return await client.create_contact(properties)  # type: ignore
        raise CRMSyncError("client does not support create_contact")
    except Exception as e:
        logger.exception("create_contact failed for %s", integration_name)
        raise


async def update_contact(integration_name: str, contact_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        if hasattr(client, "update_contact"):
            return await client.update_contact(contact_id, properties)  # type: ignore
        raise CRMSyncError("client does not support update_contact")
    except Exception as e:
        logger.exception("update_contact failed for %s id=%s", integration_name, contact_id)
        raise


async def find_contact(integration_name: str, email: str) -> Optional[Dict[str, Any]]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        return await find_contact_by_email(client, email)  # type: ignore
    except Exception as e:
        logger.exception("find_contact failed for %s email=%s", integration_name, email)
        raise


async def upsert_contact_by_email(integration_name: str, email: str, properties: Dict[str, Any]) -> Dict[str, Any]:
    svc = get_crm_sync_service()
    try:
        client = await svc.get_client(integration_name)
        return await upsert_contact_normalized(client, external_id_field="email", external_id_value=email, properties=properties)  # type: ignore
    except Exception as e:
        logger.exception("upsert_contact_by_email failed for %s email=%s", integration_name, email)
        raise


async def sync_contacts(src_integration: str, dst_integration: str, limit: int = 100, mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    svc = get_crm_sync_service()
    try:
        return await svc.sync_contacts(src_integration, dst_integration, field_mapping=mapping, limit=limit)
    except Exception as e:
        logger.exception("sync_contacts failed %s -> %s", src_integration, dst_integration)
        raise


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, default=str, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="crm_tools", description="CRM integration helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List contacts")
    p_list.add_argument("integration")
    p_list.add_argument("--query", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_get = sub.add_parser("get", help="Get contact by id")
    p_get.add_argument("integration")
    p_get.add_argument("contact_id")

    p_find = sub.add_parser("find", help="Find contact by email")
    p_find.add_argument("integration")
    p_find.add_argument("email")

    p_create = sub.add_parser("create", help="Create contact (JSON properties)")
    p_create.add_argument("integration")
    p_create.add_argument("properties", help="JSON object of properties")

    p_update = sub.add_parser("update", help="Update contact (JSON properties)")
    p_update.add_argument("integration")
    p_update.add_argument("contact_id")
    p_update.add_argument("properties", help="JSON object of properties")

    p_upsert = sub.add_parser("upsert", help="Upsert contact by email (JSON properties)")
    p_upsert.add_argument("integration")
    p_upsert.add_argument("email")
    p_upsert.add_argument("properties", help="JSON object of properties")

    p_sync = sub.add_parser("sync", help="Sync contacts between integrations")
    p_sync.add_argument("src")
    p_sync.add_argument("dst")
    p_sync.add_argument("--limit", type=int, default=100)
    p_sync.add_argument("--mapping", default=None, help="JSON mapping object {src_field:dst_field}")

    args = parser.parse_args()

    try:
        if args.cmd == "list":
            res = asyncio.run(list_contacts(args.integration, query=args.query, limit=args.limit))
            _print_json(res)
        elif args.cmd == "get":
            res = asyncio.run(get_contact(args.integration, args.contact_id))
            _print_json(res)
        elif args.cmd == "find":
            res = asyncio.run(find_contact(args.integration, args.email))
            _print_json(res)
        elif args.cmd == "create":
            props = json.loads(args.properties)
            res = asyncio.run(create_contact(args.integration, props))
            _print_json(res)
        elif args.cmd == "update":
            props = json.loads(args.properties)
            res = asyncio.run(update_contact(args.integration, args.contact_id, props))
            _print_json(res)
        elif args.cmd == "upsert":
            props = json.loads(args.properties)
            res = asyncio.run(upsert_contact_by_email(args.integration, args.email, props))
            _print_json(res)
        elif args.cmd == "sync":
            mapping = json.loads(args.mapping) if args.mapping else None
            res = asyncio.run(sync_contacts(args.src, args.dst, limit=args.limit, mapping=mapping))
            _print_json(res)
    except CRMSyncError as e:
        print("crm sync error:", str(e))
    except CRMIntegrationError as e:
        print("crm client error:", str(e))
    except Exception as exc:
        logger.exception("crm_tools error")
        print("error:", str(exc))


if __name__ == "__main__":
    main()
