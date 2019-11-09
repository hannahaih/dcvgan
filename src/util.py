from typing import Any, List, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.init as init
from joblib import Parallel, delayed
from PIL import Image
from tqdm import tqdm

from generator import ColorVideoGenerator, GeometricVideoGenerator


def current_device() -> torch.device:
    """
    Return current device (gpu or cpu)

    Returns
    -------
    device : torch.device
        Current device.
    """
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    else:
        return torch.device("cpu")


def images_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    """
    Convert pytorch images to numpy array.
        1. move tensor to cpu
        2. change axis order: (B, C, H, W) -> (B, H, W, C)
        3. change value range from [-1.0, 1.0] -> [0, 255]

    Parameters
    ----------
    tensor : torch.Tensor
        PyTorch tensor.

    Returns
    ---------
    imgs : numpy.ndarray
        Numpy array.
    """

    imgs = tensor.cpu().numpy()
    imgs = imgs.transpose(0, 2, 3, 1)
    imgs = np.clip(imgs, -1, 1)
    imgs = (imgs + 1) / 2 * 255
    imgs = imgs.astype("uint8")

    return imgs


def videos_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    """
    Convert pytorch videos to numpy array.
        1. move tensor to cpu
        2. change value range from [-1.0, 1.0] -> [0, 255]

    Parameters
    ----------
    tensor : torch.Tensor
        PyTorch tensor.

    Returns
    ---------
    imgs : numpy.ndarray
        Numpy array.
    """
    videos = tensor.cpu().numpy()
    videos = np.clip(videos, -1, 1)
    videos = (videos + 1) / 2 * 255
    videos = videos.astype("uint8")

    return videos


def make_video_grid(videos: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """
    Convert multiple videos to a single rows x cols grid video.

    Parameters
    ----------
    videos : numpy.ndarray
        Input video (axis: (B, C, T, H, W)).
        It must be len(videos) == rows*cols.

    rows : int
        Number of rows

    cols : int
        Number of columns

    Returns
    ----------
    videos : numpy.ndarray
        Grid video.
    """

    N, C, T, H, W = videos.shape
    assert N == rows * cols

    videos = videos.transpose(1, 2, 0, 3, 4)
    videos = videos.reshape(C, T, rows, cols, H, W)
    videos = videos.transpose(0, 1, 2, 4, 3, 5)
    videos = videos.reshape(C, T, rows * H, cols * W)
    videos = videos[None]

    return videos


def calc_optical_flow(video: np.ndarray) -> np.ndarray:
    """
    Calculate optical flow from a video.

    Parameters
    ----------
    videos : numpy.ndarray
        Input video (dtype: np.uint8, axis: (T, H, W, C), order: RGB).

    Returns
    ----------
    flows : numpy.ndarray
        Flow videos (dtype: np.float, axis: (T, H, W, C), shape: (T-1, H, W, 2))
    """
    flows: List[np.ndarray] = []

    for i in range(len(video) - 1):
        f1 = cv2.cvtColor(video[i], cv2.COLOR_BGR2GRAY)
        f2 = cv2.cvtColor(video[i + 1], cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(f1, f2, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        flows.append(flow)

    return np.stack(flows)


def visualize_optical_flow(flow_video: np.ndarray) -> np.ndarray:
    """
    Convert optical flow videos to color videos

    Parameters
    ----------
    flow_video : numpy.ndarray
        Input video (dtype: numpy.float, axis: (T, H, W, C)).

    Returns
    ----------
    color_video : numpy.ndarray
        Optical Flow video which represented in color
        (dtype: numpy.uint8, axis: (T, H, W, C), order: RGB).
    """
    color_video = []
    shape = list(flow_video[0].shape)
    shape[-1] = 3
    for flow in flow_video:
        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        hsv = np.zeros(shape, dtype=np.uint8)
        hsv[..., 0] = ang * 180 / np.pi / 2
        hsv[..., 1] = 255
        hsv[..., 2] = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)
        rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

        color_video.append(rgb)

    return np.stack(color_video)


class DebugLayer(nn.Module):
    """
    PyTorch module to watch intermediate feature.
    """

    def __init__(self):
        super(DebugLayer, self).__init__()

    def forward(self, x):
        print(x.shape)
        return x


def init_weights(layer: Any):
    """
    Initialize weights of Conv, BatchNorm layers using gaussian random values.
    """
    if type(layer) in [nn.Conv2d, nn.ConvTranspose2d]:
        init.normal_(layer.weight.data, 0, 0.02)
        # init.orthogonal_(layer.weight.data)
    elif type(layer) in [nn.BatchNorm2d]:
        init.normal_(layer.weight.data, 1.0, 0.02)
        init.constant_(layer.bias.data, 0.0)


def geometric_info_in_color_format(xg: np.ndarray, geometric_info: str) -> np.ndarray:
    """
    Convert geometric infomation video can be used as color video

    Parameters
    ----------
    xg : numpy.ndarray
        Geometric information video (dtype: numpy.float, axis: (B, C, T, H, W)).

    geometric_info : str
        Geometric information type

    Returns
    ----------
    xg : numpy.ndarray
        Optical Flow video which represented in color format
        (dtype: numpy.uint8, axis: (T, H, W, C), order: RGB).
    """

    if geometric_info == "depth":
        xg = np.tile(xg, (1, 3, 1, 1, 1))
        xg = (xg + 1) / 2 * 255
        xg = xg.astype("uint8")
    elif geometric_info == "optical-flow":
        B, C, T, H, W = xg.shape
        xg = xg.transpose(0, 2, 3, 4, 1)  # (B, T, H, W, C)
        xg = xg * H

        xg = Parallel(n_jobs=-1, backend="multiprocessing", verbose=0)(
            [delayed(visualize_optical_flow)(flow) for flow in xg]
        )
        xg = np.stack(xg)
        xg = xg.astype("uint8")
        xg = xg.transpose(0, 4, 1, 2, 3)  # (B, C, T, H, W)
    else:
        raise NotImplementedError

    return xg


def generate_samples(
    ggen: GeometricVideoGenerator,
    cgen: ColorVideoGenerator,
    num: int,
    batchsize: int = 20,
    verbose: bool = False,
    desc: str = "generating samples",
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate geometric info videos and color videos.

    Parameters
    ----------
    ggen : GeometricVideoGenerator
        The geometric information video generator.

    cgen : ColorVideoGenerator
        The color video generator.
    
    num : int
        Number of videos to generate.

    batchsize : int
        Batchsize.

    verbose : bool
        If true, progress bar is displayed during generating videos using tqdm.tqdm.

    desc : str
        Message displayed in the progress bar.

    Returns
    ----------
    xg : numpy.ndarray
        Optical Flow video which represented in color format
        (dtype: numpy.uint8, axis: (T, H, W, C), order: RGB).
    """

    xc_batches: List[np.ndarray] = []
    xg_batches: List[np.ndarray] = []
    for s in tqdm(range(0, num, batchsize), desc=desc, disable=not verbose):
        with torch.no_grad():
            xg = ggen.sample_videos(batchsize)
            xc = cgen.forward_videos(xg)

        xg = xg.cpu().numpy()
        xg = np.clip(xg, -1, 1)
        xc = videos_to_numpy(xc)

        xg_batches.append(xg)
        xc_batches.append(xc)

    xg = np.concatenate(xg_batches)
    xg = xg[:num]
    xg = geometric_info_in_color_format(xg, ggen.geometric_info)

    xc = np.concatenate(xc_batches)
    xc = xc[:num]

    return xg, xc
