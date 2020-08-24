import base64
import io
import os
import subprocess
import sys

if "google.colab" in sys.modules:
    os.environ["IMAGEIO_FFMPEG_EXE"] = "/usr/bin/ffmpeg"

from typing import List, Optional, Tuple

import imageio
import numpy as np
from PIL import Image
from tqdm.auto import tqdm

from habitat_sim.utils.common import d3_40_colors_rgb


def is_notebook():
    """This utility function detects if the code is running in a notebook
    """
    try:
        get_ipython = sys.modules["IPython"].get_ipython
        if "IPKernelApp" not in get_ipython().config:  # pragma: no cover
            raise ImportError("console")
        if "VSCODE_PID" in os.environ:  # pragma: no cover
            raise ImportError("vscode")
    except:
        return False
    else:
        return True


def get_fast_video_writer(video_file: str, fps: int = 60):
    if (
        "google.colab" in sys.modules
        and os.path.splitext(video_file)[-1] == ".mp4"
        and os.environ.get("IMAGEIO_FFMPEG_EXE") == "/usr/bin/ffmpeg"
    ):
        # USE GPU Accelerated Hardware Encoding
        writer = imageio.get_writer(
            video_file,
            fps=fps,
            codec="h264_nvenc",
            mode="I",
            bitrate="1000k",
            format="FFMPEG",
            ffmpeg_log_level="info",
            output_params=["-minrate", "500k", "-maxrate", "5000k"],
        )
    else:
        # Use software encoding
        writer = imageio.get_writer(video_file, fps=fps)
    return writer


def save_video(video_file: str, frames, fps: int = 60):
    """Saves the video using imageio. Will try to use GPU hardware encoding on
    Google Colab for faster video encoding. Will also display a progressbar.

    :param video_file: the file name of where to save the video
    :param frames: the actual frame objects to save
    :param fps: the fps of the video (default 60)
    """
    writer = get_fast_video_writer(video_file, fps=fps)
    for ob in tqdm(frames, desc="Encoding video:%s" % video_file):
        writer.append_data(ob)
    writer.close()


def display_video(video_file: str, height: int = 400):
    """Displays a video both locally and in a notebook. Will display the video
    as an HTML5 video if in a notebook, otherwise it opens the video file using
    the default system viewer.

    :param video_file: the filename of the video to display
    :param height: the height to display the video in a notebook.
    """
    # Check if in notebook
    if is_notebook():
        from IPython import display as ipythondisplay
        from IPython.display import HTML

        ext = os.path.splitext(video_file)[-1][1:]
        video = io.open(video_file, "r+b").read()
        ipythondisplay.display(
            HTML(
                data="""<video alt="test" autoplay
          loop controls style="height: {2}px;">
          <source src="data:video/{1}';base64,{0}" type="video/{1}" />
          </video>""".format(
                    base64.b64encode(video).decode("ascii"), ext, height
                )
            )
        )
    else:
        if sys.platform == "win32":
            os.startfile(video_file)
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.call([opener, video_file])


def make_video(
    observations: List[np.ndarray],
    primary_obs: str,
    primary_obs_type: str,
    video_file: str,
    fps: int = 60,
    open_vid: bool = True,
    video_dims: Optional[Tuple[int]] = None,
    overlay_settings=None,
    depth_clip: Optional[float] = 10.0,
):
    """Build a video from a passed observations array, with some images optionally overlayed.

    :param observations: List of observations from which the video should be constructed.
    :param primary_obs: Sensor name in observations to be used for primary video images.
    :param primary_obs_type: Primary image observation type ("color", "depth", "semantic" supported).
    :param video_file: File to save resultant .mp4 video.
    :param fps: Desired video frames per second.
    :param open_vid: Whether or not to open video upon creation.
    :param video_dims: Height by Width of video if different than observation dimensions. Applied after overlays.
    :param overlay_settings: List of settings Dicts, optional.
    :param depth_clip: Defines default depth clip normalization for all depth images.

    With **overlay_settings** dicts specifying per-entry: \n
        "type": observation type ("color", "depth", "semantic" supported)\n
        "dims": overlay dimensions (Tuple : (width, height))\n
        "pos": overlay position (top left) (Tuple : (width, height))\n
        "border": overlay image border thickness (int)\n
        "border_color": overlay image border color [0-255] (3d: array, list, or tuple). Defaults to gray [150]\n
        "obs": observation key (string)\n
    """
    videodims = observations[0][primary_obs].shape
    videodims = (videodims[1], videodims[0])  # flip to w,h order
    if not video_file.endswith(".mp4"):
        video_file = video_file + ".mp4"
    print("Encoding the video: %s " % video_file)
    writer = get_fast_video_writer(video_file, fps=fps)

    # build the border frames for the overlays and validate settings
    border_frames = []
    if overlay_settings is not None:
        for overlay in overlay_settings:
            border_image = np.zeros(
                (
                    overlay["dims"][1] + overlay["border"] * 2,
                    overlay["dims"][0] + overlay["border"] * 2,
                    3,
                ),
                np.uint8,
            )
            border_color = np.ones(3) * 150
            if "border_color" in overlay:
                border_color = np.asarray(overlay["border_color"])
            border_image[:, :] = border_color
            border_frames.append(observation_to_image(border_image, "color"))

    for ob in observations:
        # primary image processing
        image_frame = observation_to_image(ob[primary_obs], primary_obs_type)
        if image_frame is None:
            print("make_video_new : Aborting, primary image processing failed.")
            return

        # overlay images from provided settings
        if overlay_settings is not None:
            for ov_ix, overlay in enumerate(overlay_settings):
                overlay_rgb_img = observation_to_image(
                    ob[overlay["obs"]], overlay["type"], depth_clip
                )
                if overlay_rgb_img is None:
                    print(
                        'make_video_new : Aborting, overlay image processing failed on "'
                        + overlay["obs"]
                        + '".'
                    )
                    return
                overlay_rgb_img = overlay_rgb_img.resize(overlay["dims"])
                image_frame.paste(
                    border_frames[ov_ix],
                    box=(
                        overlay["pos"][0] - overlay["border"],
                        overlay["pos"][1] - overlay["border"],
                    ),
                )
                image_frame.paste(overlay_rgb_img, box=overlay["pos"])

        if video_dims is not None:
            image_frame = image_frame.resize(video_dims)

        # write the desired image to video
        writer.append_data(np.array(image_frame))

    writer.close()
    if open_vid:
        display_video(video_file)


def depth_to_rgb(depth_image: np.ndarray, clip_max: float = 10.0) -> np.ndarray:
    """Normalize depth image into [0, 1] and convert to grayscale rgb

    :param depth_image: Raw depth observation image from sensor output.
    :param clip_max: Max depth distance for clipping and normalization.

    :return: Clipped grayscale depth image data.
    """
    d_im = np.clip(depth_image, 0, clip_max)
    d_im /= clip_max
    rgb_d_im = (d_im * 255).astype(np.uint8)
    return rgb_d_im


def semantic_to_rgb(semantic_image: np.ndarray) -> np.ndarray:
    """Map semantic ids to colors and genereate an rgb image

    :param semantic_image: Raw semantic observation image from sensor output.

    :return: rgb semantic image data.
    """
    semantic_image_rgb = Image.new(
        "P", (semantic_image.shape[1], semantic_image.shape[0])
    )
    semantic_image_rgb.putpalette(d3_40_colors_rgb.flatten())
    semantic_image_rgb.putdata((semantic_image.flatten() % 40).astype(np.uint8))
    semantic_image_rgb = semantic_image_rgb.convert("RGBA")
    return semantic_image_rgb


def observation_to_image(
    observation_image: np.ndarray,
    observation_type: str,
    depth_clip: Optional[float] = 10.0,
):
    """Generate an rgb image from a sensor observation. Supported types are: "color", "depth", "semantic"

    :param observation_image: Raw observation image from sensor output.
    :param observation_type: Observation type ("color", "depth", "semantic" supported)
    :param depth_clip: Defines default depth clip normalization for all depth images.

    :return: PIL Image object or None if fails.
    """
    rgb_image = None
    if observation_type == "color":
        rgb_image = Image.fromarray(np.uint8(observation_image))
    elif observation_type == "depth":
        rgb_image = Image.fromarray(
            depth_to_rgb(observation_image, clip_max=depth_clip)
        )
    elif observation_type == "semantic":
        rgb_image = semantic_to_rgb(observation_image)
    else:
        print(
            "semantic_to_rgb : Failed, unsupported observation type: "
            + observation_type
        )
    return rgb_image
