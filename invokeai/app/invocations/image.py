# Copyright (c) 2022 Kyle Schouviller (https://github.com/kyle0654)

import io
from typing import Literal, Optional, Union

import numpy
import cv2
from PIL import Image, ImageFilter, ImageOps, ImageChops
from pydantic import BaseModel, Field

from ..models.image import ImageCategory, ImageField, ImageType
from .baseinvocation import (
    BaseInvocation,
    BaseInvocationOutput,
    InvocationContext,
    InvocationConfig,
)


class PILInvocationConfig(BaseModel):
    """Helper class to provide all PIL invocations with additional config"""

    class Config(InvocationConfig):
        schema_extra = {
            "ui": {
                "tags": ["PIL", "image"],
            },
        }


class ImageOutput(BaseInvocationOutput):
    """Base class for invocations that output an image"""

    # fmt: off
    type: Literal["image_output"] = "image_output"
    image:      ImageField = Field(default=None, description="The output image")
    width:             int = Field(description="The width of the image in pixels")
    height:            int = Field(description="The height of the image in pixels")
    # fmt: on

    class Config:
        schema_extra = {"required": ["type", "image", "width", "height"]}


class MaskOutput(BaseInvocationOutput):
    """Base class for invocations that output a mask"""

    # fmt: off
    type: Literal["mask"] = "mask"
    mask:      ImageField = Field(default=None, description="The output mask")
    width:            int = Field(description="The width of the mask in pixels")
    height:           int = Field(description="The height of the mask in pixels")
    # fmt: on

    class Config:
        schema_extra = {
            "required": [
                "type",
                "mask",
            ]
        }


class LoadImageInvocation(BaseInvocation):
    """Load an image and provide it as output."""

    # fmt: off
    type: Literal["load_image"] = "load_image"

    # Inputs
    image: Union[ImageField, None] = Field(
        default=None, description="The image to load"
    )
    # fmt: on
    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(self.image.image_type, self.image.image_name)

        return ImageOutput(
            image=ImageField(
                image_name=self.image.image_name,
                image_type=self.image.image_type,
            ),
            width=image.width,
            height=image.height,
        )


class ShowImageInvocation(BaseInvocation):
    """Displays a provided image, and passes it forward in the pipeline."""

    type: Literal["show_image"] = "show_image"

    # Inputs
    image: Union[ImageField, None] = Field(
        default=None, description="The image to show"
    )

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )
        if image:
            image.show()

        # TODO: how to handle failure?

        return ImageOutput(
            image=ImageField(
                image_name=self.image.image_name,
                image_type=self.image.image_type,
            ),
            width=image.width,
            height=image.height,
        )


class ImageCropInvocation(BaseInvocation, PILInvocationConfig):
    """Crops an image to a specified box. The box can be outside of the image."""

    # fmt: off
    type: Literal["img_crop"] = "img_crop"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to crop")
    x:      int = Field(default=0, description="The left x coordinate of the crop rectangle")
    y:      int = Field(default=0, description="The top y coordinate of the crop rectangle")
    width:  int = Field(default=512, gt=0, description="The width of the crop rectangle")
    height: int = Field(default=512, gt=0, description="The height of the crop rectangle")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        image_crop = Image.new(
            mode="RGBA", size=(self.width, self.height), color=(0, 0, 0, 0)
        )
        image_crop.paste(image, (-self.x, -self.y))

        image_dto = context.services.images.create(
            image=image_crop,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class ImagePasteInvocation(BaseInvocation, PILInvocationConfig):
    """Pastes an image into another image."""

    # fmt: off
    type: Literal["img_paste"] = "img_paste"

    # Inputs
    base_image:     Union[ImageField, None]  = Field(default=None, description="The base image")
    image:          Union[ImageField, None]  = Field(default=None, description="The image to paste")
    mask: Optional[ImageField] = Field(default=None, description="The mask to use when pasting")
    x:                     int = Field(default=0, description="The left x coordinate at which to paste the image")
    y:                     int = Field(default=0, description="The top y coordinate at which to paste the image")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        base_image = context.services.images.get_pil_image(
            self.base_image.image_type, self.base_image.image_name
        )
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )
        mask = (
            None
            if self.mask is None
            else ImageOps.invert(
                context.services.images.get_pil_image(
                    self.mask.image_type, self.mask.image_name
                )
            )
        )
        # TODO: probably shouldn't invert mask here... should user be required to do it?

        min_x = min(0, self.x)
        min_y = min(0, self.y)
        max_x = max(base_image.width, image.width + self.x)
        max_y = max(base_image.height, image.height + self.y)

        new_image = Image.new(
            mode="RGBA", size=(max_x - min_x, max_y - min_y), color=(0, 0, 0, 0)
        )
        new_image.paste(base_image, (abs(min_x), abs(min_y)))
        new_image.paste(image, (max(0, self.x), max(0, self.y)), mask=mask)

        image_dto = context.services.images.create(
            image=new_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class MaskFromAlphaInvocation(BaseInvocation, PILInvocationConfig):
    """Extracts the alpha channel of an image as a mask."""

    # fmt: off
    type: Literal["tomask"] = "tomask"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to create the mask from")
    invert:      bool = Field(default=False, description="Whether or not to invert the mask")
    # fmt: on

    def invoke(self, context: InvocationContext) -> MaskOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        image_mask = image.split()[-1]
        if self.invert:
            image_mask = ImageOps.invert(image_mask)

        image_dto = context.services.images.create(
            image=image_mask,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.MASK,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return MaskOutput(
            mask=ImageField(
                image_type=image_dto.image_type, image_name=image_dto.image_name
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class ImageMultiplyInvocation(BaseInvocation, PILInvocationConfig):
    """Multiplies two images together using `PIL.ImageChops.multiply()`."""

    # fmt: off
    type: Literal["img_mul"] = "img_mul"

    # Inputs
    image1: Union[ImageField, None]  = Field(default=None, description="The first image to multiply")
    image2: Union[ImageField, None]  = Field(default=None, description="The second image to multiply")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image1 = context.services.images.get_pil_image(
            self.image1.image_type, self.image1.image_name
        )
        image2 = context.services.images.get_pil_image(
            self.image2.image_type, self.image2.image_name
        )

        multiply_image = ImageChops.multiply(image1, image2)

        image_dto = context.services.images.create(
            image=multiply_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_type=image_dto.image_type, image_name=image_dto.image_name
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


IMAGE_CHANNELS = Literal["A", "R", "G", "B"]


class ImageChannelInvocation(BaseInvocation, PILInvocationConfig):
    """Gets a channel from an image."""

    # fmt: off
    type: Literal["img_chan"] = "img_chan"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to get the channel from")
    channel: IMAGE_CHANNELS  = Field(default="A", description="The channel to get")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        channel_image = image.getchannel(self.channel)

        image_dto = context.services.images.create(
            image=channel_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_type=image_dto.image_type, image_name=image_dto.image_name
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


IMAGE_MODES = Literal["L", "RGB", "RGBA", "CMYK", "YCbCr", "LAB", "HSV", "I", "F"]


class ImageConvertInvocation(BaseInvocation, PILInvocationConfig):
    """Converts an image to a different mode."""

    # fmt: off
    type: Literal["img_conv"] = "img_conv"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to convert")
    mode: IMAGE_MODES  = Field(default="L", description="The mode to convert to")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        converted_image = image.convert(self.mode)

        image_dto = context.services.images.create(
            image=converted_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_type=image_dto.image_type, image_name=image_dto.image_name
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class ImageBlurInvocation(BaseInvocation, PILInvocationConfig):
    """Blurs an image"""

    # fmt: off
    type: Literal["img_blur"] = "img_blur"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to blur")
    radius:     float = Field(default=8.0, ge=0, description="The blur radius")
    blur_type: Literal["gaussian", "box"] = Field(default="gaussian", description="The type of blur")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        blur = (
            ImageFilter.GaussianBlur(self.radius)
            if self.blur_type == "gaussian"
            else ImageFilter.BoxBlur(self.radius)
        )
        blur_image = image.filter(blur)

        image_dto = context.services.images.create(
            image=blur_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class ImageLerpInvocation(BaseInvocation, PILInvocationConfig):
    """Linear interpolation of all pixels of an image"""

    # fmt: off
    type: Literal["img_lerp"] = "img_lerp"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to lerp")
    min: int = Field(default=0, ge=0, le=255, description="The minimum output value")
    max: int = Field(default=255, ge=0, le=255, description="The maximum output value")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        image_arr = numpy.asarray(image, dtype=numpy.float32) / 255
        image_arr = image_arr * (self.max - self.min) + self.max

        lerp_image = Image.fromarray(numpy.uint8(image_arr))

        image_dto = context.services.images.create(
            image=lerp_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )


class ImageInverseLerpInvocation(BaseInvocation, PILInvocationConfig):
    """Inverse linear interpolation of all pixels of an image"""

    # fmt: off
    type: Literal["img_ilerp"] = "img_ilerp"

    # Inputs
    image: Union[ImageField, None]  = Field(default=None, description="The image to lerp")
    min: int = Field(default=0, ge=0, le=255, description="The minimum input value")
    max: int = Field(default=255, ge=0, le=255, description="The maximum input value")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        image_arr = numpy.asarray(image, dtype=numpy.float32)
        image_arr = (
            numpy.minimum(
                numpy.maximum(image_arr - self.min, 0) / float(self.max - self.min), 1
            )
            * 255
        )

        ilerp_image = Image.fromarray(numpy.uint8(image_arr))

        image_dto = context.services.images.create(
            image=ilerp_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
            is_intermediate=self.is_intermediate,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )

class HueAdjustmentInvocation(BaseInvocation):
    """Adjusts the Hue of an image."""

    # fmt: off
    type: Literal["hue_adjust"] = "hue_adjust"

    # Inputs
    image: ImageField = Field(default=None, description="The image to adjust")
    hue: float = Field(default=0, description="The degrees by which to rotate the hue")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        pil_image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        # Convert PIL image to OpenCV format (numpy array), note color channel
        # ordering is changed from RGB to BGR
        image = numpy.array(pil_image.convert('RGB'))[:, :, ::-1]

        # Convert image to HSV color space
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Adjust the hue
        hsv_image[:, :, 0] = (hsv_image[:, :, 0] + self.hue) % 180

        # Convert image back to BGR color space
        image = cv2.cvtColor(hsv_image, cv2.COLOR_HSV2BGR)

        # Convert back to PIL format and to original color mode
        pil_image = Image.fromarray(image[:, :, ::-1], 'RGB').convert('RGBA')

        image_dto = context.services.images.create(
            image=pil_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )

class LuminosityAdjustmentInvocation(BaseInvocation):
    """Adjusts the Luminosity (Value) of an image."""

    # fmt: off
    type: Literal["luminosity_adjust"] = "luminosity_adjust"

    # Inputs
    image: ImageField = Field(default=None, description="The image to adjust")
    luminosity: float = Field(default=1.0, description="The factor by which to adjust the luminosity (value)")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        pil_image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        # Convert PIL image to OpenCV format (numpy array), note color channel
        # ordering is changed from RGB to BGR
        image = numpy.array(pil_image.convert('RGB'))[:, :, ::-1]

        # Convert image to HSV color space
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Adjust the luminosity (value)
        hsv_image[:, :, 2] = numpy.clip(hsv_image[:, :, 2] * self.luminosity, 0, 255)

        # Convert image back to BGR color space
        image = cv2.cvtColor(hsv_image, cv2.COLOR_HSV2BGR)

        # Convert back to PIL format and to original color mode
        pil_image = Image.fromarray(image[:, :, ::-1], 'RGB').convert('RGBA')

        image_dto = context.services.images.create(
            image=pil_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )

class SaturationAdjustmentInvocation(BaseInvocation):
    """Adjusts the Saturation of an image."""

    # fmt: off
    type: Literal["saturation_adjust"] = "saturation_adjust"

    # Inputs
    image: ImageField = Field(default=None, description="The image to adjust")
    saturation: float = Field(default=1.0, description="The factor by which to adjust the saturation")
    # fmt: on

    def invoke(self, context: InvocationContext) -> ImageOutput:
        pil_image = context.services.images.get_pil_image(
            self.image.image_type, self.image.image_name
        )

        # Convert PIL image to OpenCV format (numpy array), note color channel
        # ordering is changed from RGB to BGR
        image = numpy.array(pil_image.convert('RGB'))[:, :, ::-1]

        # Convert image to HSV color space
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # Adjust the saturation
        hsv_image[:, :, 1] = numpy.clip(hsv_image[:, :, 1] * self.saturation, 0, 255)

        # Convert image back to BGR color space
        image = cv2.cvtColor(hsv_image, cv2.COLOR_HSV2BGR)

        # Convert back to PIL format and to original color mode
        pil_image = Image.fromarray(image[:, :, ::-1], 'RGB').convert('RGBA')

        image_dto = context.services.images.create(
            image=pil_image,
            image_type=ImageType.RESULT,
            image_category=ImageCategory.GENERAL,
            node_id=self.id,
            session_id=context.graph_execution_state_id,
        )

        return ImageOutput(
            image=ImageField(
                image_name=image_dto.image_name,
                image_type=image_dto.image_type,
            ),
            width=image_dto.width,
            height=image_dto.height,
        )
