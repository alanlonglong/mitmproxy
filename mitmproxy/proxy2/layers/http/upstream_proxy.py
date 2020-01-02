from typing import Optional, Tuple

from h11._receivebuffer import ReceiveBuffer

from mitmproxy import http
from mitmproxy.net.http import http1
from mitmproxy.net.http.http1 import read_sansio as http1_sansio
from mitmproxy.proxy2 import commands, context, events, layer, tunnel
from mitmproxy.utils import human


class HttpUpstreamProxy(tunnel.TunnelLayer):
    buf: ReceiveBuffer

    def __init__(self, ctx: context.Context, address: tuple):
        s = context.Server(address)
        ctx.server.via = (*ctx.server.via, s)
        super().__init__(ctx, tunnel_connection=s, conn=ctx.server)
        self.buf = ReceiveBuffer()

    def start_handshake(self) -> layer.CommandGenerator[None]:
        req = http.make_connect_request(self.conn.address)
        raw = http1.assemble_request(req)
        yield commands.SendData(self.tunnel_connection, raw)

    def receive_handshake_data(self, data: bytes) -> layer.CommandGenerator[Tuple[bool, Optional[str]]]:
        self.buf += data
        response_head = self.buf.maybe_extract_lines()
        if response_head:
            response_head = [bytes(x) for x in response_head]  # TODO: Make url.parse compatible with bytearrays
            try:
                response = http.HTTPResponse.wrap(http1_sansio.read_response_head(response_head))
            except ValueError as e:
                yield commands.Log(f"{human.format_address(self.tunnel_connection.address)}: {e}")
                return False, str(e)
            if 200 <= response.status_code < 300:
                if self.buf:
                    yield from self.receive_data(bytes(self.buf))
                    del self.buf
                return True, None
            else:
                raw_resp = b"\n".join(response_head)
                yield commands.Log(f"{human.format_address(self.tunnel_connection.address)}: {raw_resp}", level="debug")
                return False, f"{response.status_code} {response.reason}"
        else:
            return False, None