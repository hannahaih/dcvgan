import datetime
import enum
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

import colorlog
import numpy as np
import torch
from tensorboardX import SummaryWriter


class MetricType(enum.IntEnum):
    """
    Enum class for logging metric.
    """

    Integer = 1
    Float = 2
    Loss = 3
    Time = 4


class Metric(object):
    """
    Meric class for logging.

    Parameters
    ----------
    mtype : MetricType
        Metric type.

    priority : int
        Metric priority to determine display order.

    tensorboard : bool
        If true, the metric is logged into tensorboard too.
    """

    mtype_list: List[int] = list(map(int, MetricType))

    def __init__(self, mtype: MetricType, priority: int, tensorboard: bool):
        if mtype not in self.mtype_list:
            raise Exception(f"mtype is invalid, {self.mtype_list}")

        self.mtype: MetricType = mtype
        self.params: Dict[str, Any] = {}
        self.priority: int = priority
        self.log_to_tensorboard: bool = tensorboard
        self.value: Any = 0


class Logger(object):
    """
    Original logger.

    Parameters
    ----------
    out_path : pathlib.Path
        Path object to write log outputs.

    tb_path : pathlib.Path
        Path object to save TensorBoard logging object.
    """

    def __init__(self, out_path: Path, tb_path: Path):
        # initialize logging module
        out_path.mkdir(parents=True, exist_ok=True)
        self.path = out_path

        self._logger: logging.Logger = self.new_logging_module(
            __name__, out_path / "log"
        )

        # logging metrics
        self.metrics: OrderedDict[str, Metric] = OrderedDict()

        # tensorboard writer
        tb_path.mkdir(parents=True, exist_ok=True)
        self.tb_path = tb_path
        self.tf_writer: SummaryWriter = SummaryWriter(str(tb_path))

        # automatically add elapsed_time metric
        self.define("epoch", MetricType.Integer, 100, False)
        self.define("iteration", MetricType.Integer, 99, False)
        self.define("elapsed_time", MetricType.Time, -1, False)

        self.indent = " " * 4

    def new_logging_module(self, name: str, log_file: Path) -> logging.Logger:
        """
        Returns base logging module with logging.Logger

        Parameters
        ----------
        name : str
            Logger identifier.

        log_file : pathlib.Path
            Path object to write log outputs.
        """
        # specify format
        log_format: str = "[%(asctime)s] %(message)s"
        date_format: str = "%Y-%m-%d %H:%M:%S"

        # init module
        logger: logging.Logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)

        # console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s" + log_format, datefmt=date_format
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # file handler
        fh = logging.FileHandler(str(log_file))
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(log_format, datefmt=date_format)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        return logger

    def _log(self):
        log_strings: List[str] = []
        for k, m in self.metrics.items():
            # console (or file ) logging
            if m.mtype == MetricType.Integer:
                if m.value is None:
                    s = "-"
                else:
                    s = "{}".format(m.value)
            if m.mtype == MetricType.Float:
                if m.value is None:
                    s = "-"
                else:
                    s = "{:0.3f}".format(m.value)
            elif m.mtype == MetricType.Loss:
                if len(m.value) == 0:
                    s = " - "
                else:
                    s = "{:0.3f}".format(sum(m.value) / len(m.value))
            elif m.mtype == MetricType.Time:
                _value = int(m.value)
                s = str(datetime.timedelta(seconds=_value))

            log_strings.append(s)

        log_string: str = ""
        for s in log_strings:
            log_string += "{:>15} ".format(s)

        self.info(log_string)

    def log(self, x_axis_metric: str = "iteration"):
        """
        Print registerd metrics to console, file, tensorboard.

        Parameters
        ----------
        x_axis_metric : str
            Metric to be used as x-axis.
        """
        self.update("elapsed_time", time.time())

        # tensorboard
        self.tf_log_scalars(x_axis_metric)

        # console
        self._log()

    def define(self, name: str, mtype: MetricType, priority=0, tensorboard=True):
        """
        Register a new metric.

        Parameters
        ----------
        name : str
            Metric name.

        mtype : MetricType
            Metric type (integer, float, loss, time).

        priority : int
            Metric priority.

        tensorboard : bool
            If true, the metric is logged into tensorboard too.
        """
        metric: Metric = Metric(mtype, priority, tensorboard)
        if mtype in [MetricType.Integer, MetricType.Float]:
            metric.value = None
        elif mtype == MetricType.Loss:
            metric.value = []
        elif mtype == MetricType.Time:
            metric.value = 0
            metric.params["start_time"] = time.time()
        self.metrics[name] = metric

        self.metrics = OrderedDict(
            sorted(self.metrics.items(), key=lambda m: m[1].priority, reverse=True)
        )

    def metric_keys(self) -> List[str]:
        """
        Return all registerd metrics.
        """
        return list(self.metrics.keys())

    def clear(self):
        """
        Initialize all registerd metrics.
        """
        for _, metric in self.metrics.items():
            if metric.mtype in [MetricType.Integer, MetricType.Float]:
                metric.value = None
            elif metric.mtype == MetricType.Loss:
                metric.value = []

    def update(self, name: str, value: Any):
        """
        Update or add new metric value.

        Parameters
        ----------
        name : str
            Metric name.

        value : Any
            Metric value.
        """
        m = self.metrics[name]
        if m.mtype in [MetricType.Integer, MetricType.Float]:
            m.value = value
        elif m.mtype == MetricType.Loss:
            m.value.append(value)
        elif m.mtype == MetricType.Time:
            m.value = value - m.params["start_time"]

    def print_header(self):
        """
        Print header of training progress.
        """
        log_string = ""
        for name in self.metrics.keys():
            log_string += "{:>15} ".format(name)
        self.info(log_string)

    def tf_log_scalars(self, x_axis_metric: str):
        """
        Add all registered metric values to TensorBoard.

        Parameters
        ----------
        x_axis_metric : str
            Metric to be used as x-axis.
        """
        if x_axis_metric not in self.metric_keys():
            raise Exception(f"No such metric: {x_axis_metric}")

        x_metric = self.metrics[x_axis_metric]
        if x_metric.mtype not in [MetricType.Integer, MetricType.Float]:
            raise Exception(f"Invalid metric type: {repr(x_metric.mtype)}")

        step = x_metric.value
        for name, metric in self.metrics.items():
            if not metric.log_to_tensorboard:
                continue

            if metric.mtype in [MetricType.Integer, MetricType.Float]:
                if metric.value is None:
                    continue
                value = metric.value
            elif metric.mtype == MetricType.Loss:
                if len(metric.value) == 0:
                    continue
                value = sum(metric.value) / len(metric.value)

            self.tf_writer.add_scalar(name, value, step)

    def tf_log_histgram(self, x: np.ndarray, tag: str, step: int):
        """
        Add histgram of input tensor to TensorBoard.

        Parameters
        ----------
        x : np.ndarray
            Input tensor.

        tag : str
            Data identifier.

        step : int
            Global step value to record.
        """
        self.tf_writer.add_histogram(tag, x, step)

    def tf_log_image(self, x: np.ndarray, tag: str, step: int):
        """
        Add image to TensorBoard.

        Parameters
        ----------
        x : np.ndarray
            Input image (dtype: uint8, axis: (B, C, H, W), order: RGB).

        tag : str
            Data identifier.

        step : int
            Global step value to record.
        """
        self.tf_writer.add_image(tag, x, step)

    def tf_log_video(self, x: np.ndarray, tag: str, step: int):
        """
        Add video as GIF image to TensorBoard.

        Parameters
        ----------
        x : np.ndarray
            Input video (dtype: uint8, axis: (B, T, C, H, W), order: RGB).

        tag : str
            Data identifier.

        step : int
            Global step value to record.
        """
        self.tf_writer.add_video(tag, x, fps=8, global_step=step)

    def tf_log_hparams(self, values: Dict[str, Any]):
        """
        Add hyper parameters to TensorBoard.

        Parameters
        ----------
        values : Dict[str, Any]
            Dict contains hyper parameters
        """
        self.tf_writer.add_hparams(values, {})

    def info(self, msg: str, level=0):
        self._logger.info(self.indent * level + msg)

    def debug(self, msg: str, level=0):
        self._logger.debug(self.indent * level + msg)

    def warning(self, msg: str, level=0):
        self._logger.warning(self.indent * level + msg)

    def error(self, msg: str, level=0):
        self._logger.error(self.indent * level + msg)

    def critical(self, msg: str, level=0):
        self._logger.critical(self.indent * level + msg)
