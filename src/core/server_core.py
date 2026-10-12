import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional

from src.core.description import global_get_private_data
from src.log.loggers import EndpointLogger, ExtendedLevelsLogger
from src.services.meshtastic import MeshtasticWireHandleThread
from src.core.private_config import EndpointPrivateConfig
from src.wav.streams_storage import StreamsStorage
from src.core.core_threading import IOQueuedThread
from src.services.tox import ToxClientThread
from src.core.structs import with_mutex


class ServerCoreException(Exception):
    pass


@dataclass
class EndpointPrivateHandlerObject:
    streams_storage: StreamsStorage
    private_data: EndpointPrivateConfig
    logger: EndpointLogger
    tox_instance: ToxClientThread = None
    smms_instance: ToxClientThread = None
    meshtastic_instances: Dict[str, MeshtasticWireHandleThread] = field(default_factory=dict)
    meshcore_instances: Dict[str, IOQueuedThread] = field(default_factory=dict)


class ServerCore:
    def __init__(self, private_key: str):
        self._private_data = global_get_private_data(private_key)
        self._logger = ExtendedLevelsLogger(self._private_data.detetime_fmt, self._private_data.timezone, self._private_data.logger_name, self._private_data.log_fmt)
        if self._private_data.logger_visualize_colour_scheme:
            self._logger.visualize()
        self._core_mutex = threading.RLock()

        self._handler = EndpointPrivateHandlerObject(
        streams_storage=StreamsStorage(
        clear_interval=timedelta(seconds=self._private_data.http_session_lifetime),
        stream_lifetime=timedelta(seconds=self._private_data.http_session_lifetime),
        logger=self._logger),
        private_data=self._private_data,
        logger=self._logger)

        self.init_core_threads()

    def get_handler(self) -> EndpointPrivateHandlerObject:
        return self._handler

    @property
    def core_mutex(self) -> threading.Lock:
        return self._core_mutex

    @property
    def logger(self) -> EndpointLogger:
        return self._logger

    @property
    def private_data(self) -> EndpointPrivateConfig:
        return self._private_data

    def get_working_instances(self, instances: Dict[str, IOQueuedThread], service_name: str, pop: bool = True) -> List[IOQueuedThread]:
        result_instances: List[IOQueuedThread] = []
        for instance_name in list(instances.keys()):
            instance = instances.get(instance_name)
            if instance.is_finalizable and instance.ident is not None:
                result_instances.append(instances.pop(instance_name) if pop else instance)
        self._logger.note(f"From {service_name} instances were added to threads for finalization list: {[ri.name for ri in result_instances] if result_instances else 'Not a single'}")
        return result_instances

    @with_mutex("core_mutex", wait=False)
    def init_core_threads(self) -> None:
        self._logger.core(f"Creating all instance threads")

        if self._private_data.tox_config:
            try:
                self._handler.tox_instance = ToxClientThread(self._logger, self._private_data.tox_config)
            except Exception as exp:
                self._handler.logger.exception(f"Exception while initialization tox instance thread: {exp}")

        if self._private_data.meshtastic_nodes:
                for node_config in self._private_data.meshtastic_nodes.values():
                    try:
                        self._handler.meshtastic_instances[node_config.short_name] = MeshtasticWireHandleThread(self._logger, node_config)
                    except Exception as exp:
                        self._handler.logger.exception(f"Exception while initialization meshtastic instance: {exp}, thread: {node_config.short_name}")

    @with_mutex("core_mutex", wait=False)
    def start_core_threads(self) -> None:
        self._logger.core(f"Starting all instance waiting threads")
        if self._handler.tox_instance:
            if not self._handler.tox_instance.is_alive():
                self._handler.tox_instance.start()
        for mi in self._handler.meshtastic_instances.values():
            mi.start()

    @with_mutex("core_mutex", wait=False)
    def stop_core_threads(self, join_time: float = 2.500, max_iterations_count: int = 16) -> Optional[List[IOQueuedThread]]:
        self._logger.core("Creating thread finalization list for complete stoppage of all running threads")
        working_threads: List[IOQueuedThread] = list()
        if self._handler.tox_instance and self._handler.tox_instance.is_finalizable:
            working_threads.append(self._handler.tox_instance)
            self._logger.note("Tox instance was added to threads for finalization list")
        if self._handler.smms_instance and self._handler.smms_instance.is_finalizable:
            working_threads.append(self._handler.smms_instance)
            self._logger.note("SMMS instance was added to threads for finalization list")
        working_threads += self.get_working_instances(self._handler.meshtastic_instances, "meshtastic")
        working_threads += self.get_working_instances(self._handler.meshcore_instances, "meshcore")

        if not working_threads:
            self._logger.core("Noone running thread for finalization not found, aborting")
            return
        self._logger.core(f"Starting finalization of all running threads: {len(working_threads)}")
        for working_thread in working_threads:
            working_thread.finalize()

        loop_counter: int = 0
        self._logger.core(f"Starting waiting for all threads stopped loop with join time: {join_time} sec, max iterations count: {max_iterations_count}")
        while working_threads:
            per_thread_timeout = join_time / len(working_threads)
            self._logger.debug(f"Join timeout per thread now is: {per_thread_timeout}")
            loop_counter += 1
            if loop_counter == max_iterations_count:
                self._logger.error(
                    f"Loop waiting for all threads stopped completed, but threads: {[t.name for t in working_threads]} not stopped, returning it's list")
                return working_threads
            self._logger.debug(f"Running {loop_counter}/{max_iterations_count} iteration of waiting for all threads stopped loop")
            stopping_threads: List[IOQueuedThread] = list()
            for working_thread in working_threads:
                try:
                    working_thread.join(timeout=max(0.01, per_thread_timeout))
                    if not working_thread.is_alive():
                        stopping_threads.append(working_thread)
                except RuntimeError:
                    pass
            for stopped_thread in stopping_threads:
                self._logger.note(f"Thread {stopped_thread.name} was stopped")
                working_threads.remove(stopped_thread)
        self._logger.core("Waiting for all threads stopped loop was successfully completed!")

    @with_mutex("core_mutex", wait=False)
    def restart(self) -> None:
        self._logger.info("Restarting all threads")
        self.stop_core_threads()
        self.init_core_threads()
        self.start_core_threads()
        self._logger.info("All threads was restarted")
