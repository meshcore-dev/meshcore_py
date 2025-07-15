import asyncio
import logging
from .events import Event, EventType

logger = logging.getLogger("meshcore")

class BinaryCommandHandler :
    """ Helper functions to handle binary requests through binary commands """
    def __init__ (self, c):
        self.commands = c

    @property
    def dispatcher(self):
        return self.commands.dispatcher

    async def req_binary (self, contact, request) :
        res = await self.commands.send_binary_req(contact, request)
        logger.debug(res)
        if res.type == EventType.ERROR:
            logger.error(f"Error while requesting binary data")
            return None
        else:
            exp_tag = res.payload["expected_ack"].hex()
            timeout = res.payload["suggested_timeout"] / 1000
            res2 = await self.dispatcher.wait_for_event(EventType.BINARY_RESPONSE, attribute_filters={"tag": exp_tag}, timeout=timeout)
            logger.debug(res2)
            if res2 is None :
                return None
            else:
                return res2.payload
