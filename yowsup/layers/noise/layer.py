

from yowsup.layers.noise.workers.handshake import WANoiseProtocolHandshakeWorker
from yowsup.layers import YowLayer, EventCallback
from yowsup.layers.auth.layer_authentication import YowAuthenticationProtocolLayer
from yowsup.layers.network.layer import YowNetworkLayer
from yowsup.layers.noise.layer_noise_segments import YowNoiseSegmentsLayer

from noisewa.protocol import WANoiseProtocol
from noisewa.config.client import ClientConfig
from noisewa.config.templates.useragent_vbox import VBoxUserAgentConfig
from noisewa.streams.segmented.blockingqueue import BlockingQueueSegmentedStream
from noisewa.structs.publickey import PublicKey
from noisewa.structs.keypair import KeyPair
import threading
import base64
import logging


logger = logging.getLogger(__name__)
try:
    import Queue
except ImportError:
    import queue as Queue


class YowNoiseLayer(YowLayer):
    HEADER = b'WA\x02\x01'

    def __init__(self):
        super(YowNoiseLayer, self).__init__()
        self._wa_noiseprotocol = WANoiseProtocol(
            2, 1, protocol_state_callbacks=self._on_protocol_state_changed
        )  # type: WANoiseProtocol

        self._handshake_worker = None
        self._stream = BlockingQueueSegmentedStream() # type: BlockingQueueSegmentedStream
        self._read_buffer = bytearray()
        self._flush_lock = threading.Lock()
        self._incoming_segments_queue = Queue.Queue()

    def __str__(self):
        return "Noise Layer"

    @EventCallback(YowNetworkLayer.EVENT_STATE_DISCONNECTED)
    def on_disconnected(self, event):
        self._wa_noiseprotocol.reset()

    @EventCallback(YowAuthenticationProtocolLayer.EVENT_AUTH)
    def on_auth(self, event):
        logger.debug("Received auth event")
        username = int(event.getArg('username'))
        passive = event.getArg('passive')

        self.setProp(YowNoiseSegmentsLayer.PROP_ENABLED, False)
        self.toLower(self.HEADER)
        self.setProp(YowNoiseSegmentsLayer.PROP_ENABLED, True)

        remote_static = PublicKey(
            base64.b64decode(
                b"8npJs5ulcmDmDaHZYflOveqXO73Gg2CzJySKvDs6qh4="
            )
        )
        local_static = KeyPair.from_bytes(
            base64.b64decode(
                b"MA9j0UP4lJwKWPtHcwSg+DTjM8HG0HI9k+vIMoxDiGHs59Xqht7dsss4K0PgyDKsxm6UwjwbG9Kgdit3iQiFRQ=="
            )
        )
        client_config = ClientConfig(
            username=username,
            passive=passive,
            useragent=VBoxUserAgentConfig("2.19.51"),
            pushname="virus",
            short_connect=True
        )
        if not self._in_handshake():
            logger.debug("Performing handshake [username= %d, passive=%s]" % (username, passive) )
            self._handshake_worker = WANoiseProtocolHandshakeWorker(
                self._wa_noiseprotocol, self._stream, client_config, local_static, remote_static,
            )
            logger.debug("Starting handshake worker")
            self._stream.set_events_callback(self._handle_stream_event)
            self._handshake_worker.start()

    def _in_handshake(self):
        """
        :return:
        :rtype: bool
        """
        return self._wa_noiseprotocol.state == WANoiseProtocol.STATE_HANDSHAKE

    def _on_protocol_state_changed(self, state):
        if state == WANoiseProtocol.STATE_TRANSPORT:
            self._flush_incoming_buffer()

    def _handle_stream_event(self, event):
        if event == BlockingQueueSegmentedStream.EVENT_WRITE:
            self.toLower(self._stream.get_write_segment())
        elif event == BlockingQueueSegmentedStream.EVENT_READ:
            self._stream.put_read_segment(self._incoming_segments_queue.get(block=True))

    def send(self, data):
        """
        :param data:
        :type data: bytearray | bytes
        :return:
        :rtype:
        """
        data = bytes(data) if type(data) is not bytes else data
        self._wa_noiseprotocol.send(data)

    def _flush_incoming_buffer(self):
        self._flush_lock.acquire(blocking=True)
        while self._incoming_segments_queue.qsize():
            self.toUpper(self._wa_noiseprotocol.receive())
        self._flush_lock.release()

    def receive(self, data):
        """
        :param data:
        :type data: bytes
        :return:
        :rtype:
        """
        self._incoming_segments_queue.put(data)
        if not self._in_handshake():
            self._flush_incoming_buffer()
