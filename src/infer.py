import argparse
from pathlib import Path

import torch
import torch.nn as nn
import yaml
from joblib import Parallel, delayed
from tqdm import tqdm

import dataio
import util


def load_model(model_path: Path, params_path: Path) -> nn.Module:
    """
    Load a pytorch module with trained weights.

    Parameters
    ----------
    model_path : pathlib.Path
        Path object of the model class pickle.

    params_path : pathlib.Path
        Path object of the model weight pickle.

    Returns
    -------
    model : nn.Module
        Trained model.
    """
    model = torch.load(model_path, map_location="cpu")
    params = torch.load(params_path, map_location="cpu")
    model.load_state_dict(params)
    model = model.to(util.current_device())
    model.device = util.current_device()
    model.eval()

    return model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("iteration", type=int)
    parser.add_argument("save_dir", type=Path)
    parser.add_argument("--n_samples", "-n", type=int, default=10000)
    parser.add_argument("--batchsize", "-b", type=int, default=10)
    args = parser.parse_args()

    # read config file
    with open(args.result_dir / "config.yml") as f:
        configs = yaml.load(f, Loader=yaml.FullLoader)

    # load model with weights
    ggen = load_model(
        args.result_dir / "models" / "ggen_model.pth",
        args.result_dir / "models" / f"ggen_params_{args.iteration:05d}.pth",
    )
    cgen = load_model(
        args.result_dir / "models" / "cgen_model.pth",
        args.result_dir / "models" / f"cgen_params_{args.iteration:05d}.pth",
    )

    # make directories
    color_dir = args.save_dir / "color"
    color_dir.mkdir(parents=True, exist_ok=True)
    geo_dir = args.save_dir / configs["geometric_info"]["name"]
    geo_dir.mkdir(parents=True, exist_ok=True)

    # generate samples
    for offset in tqdm(range(0, args.n_samples, args.batchsize)):
        xg, xc = util.generate_samples(
            ggen, cgen, args.batchsize, args.batchsize, verbose=False
        )

        # (B, C, T, H, W) -> (B, T, H, W, C)
        xg, xc = xg.transpose(0, 2, 3, 4, 1), xc.transpose(0, 2, 3, 4, 1)

        dataio.write_videos_pararell(
            xg, [geo_dir / "{:06d}.mp4".format(offset + i) for i in range(len(xg))]
        )
        dataio.write_videos_pararell(
            xc, [color_dir / "{:06d}.mp4".format(offset + i) for i in range(len(xc))]
        )


if __name__ == "__main__":
    main()
