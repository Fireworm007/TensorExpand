# -*- coding: utf8 -*-

'''
注意：
0、如果训练新的数据只需修改ShapesConfig与ShapesDataset类，其他不动

1、传入的图片大小必须是2^6的倍数，如：64,128,256……(64*n n=1,2,3,……)，且必须是3波段，如果进入`config.py`修改波段，后面运算会报错（不解）

2、图片对应的掩膜图片大小为对应原图的大小，背景像素为0，对象内的像素为1 即0、1像素图片，图像shape[h,w,3] ;mask shape [h,w,instance count]

3、mnist图片大小28x28x1，类别数0~9 10类 加上背景 共11类（这种模式[图像分割]必须算上背景作为一个类别）**注**：背景默认class为0，0~9 数字对应的标签为1~10

4、先将mnist图片从28x28 resize到32x32 ，再组成4x4的图片，新的图片大小32x4=128

5、masks:[height, width, instance count]  这里height=width=128，instance count=16（4x4每个格都有对象）

6、class_ids: a 1D array of class IDs of the instance masks. [instance count,] 要与mask对应起来

7、输入：图片[h,w,3]，图片每个对象的掩膜[h,w,instance count]，每个对象的class_id[instance count,] (从1开始标记，0默认为背景)  
'''

import os
import sys
import random
import math
import re
import time
import numpy as np
import cv2
import matplotlib
import matplotlib.pyplot as plt

from config import Config
import utils
import model as modellib
import visualize
from model import log
from tensorflow.examples.tutorials.mnist.input_data import read_data_sets

mnist=read_data_sets('./MNIST_data',one_hot=False)

# %matplotlib inline

# Root directory of the project
ROOT_DIR = os.getcwd()

# Directory to save logs and trained model
MODEL_DIR = os.path.join(ROOT_DIR, "logs")

# Local path to trained weights file
COCO_MODEL_PATH = os.path.join(ROOT_DIR, "mask_rcnn_coco.h5")
# Download COCO trained weights from Releases if needed
if not os.path.exists(COCO_MODEL_PATH):
    utils.download_trained_weights(COCO_MODEL_PATH)


class ShapesConfig(Config):
    """Configuration for training on the toy shapes dataset.
    Derives from the base Config class and overrides values specific
    to the toy shapes dataset.
    玩具形状数据集的训练配置。
     派生自基础Config类并覆盖特定值
     到玩具形状数据集。
    """
    # Give the configuration a recognizable name
    # 给配置一个可识别的名字
    NAME = "shapes"

    # Train on 1 GPU and 8 images per GPU. We can put multiple images on each
    # GPU because the images are small. Batch size is 8 (GPUs * images/GPU).
    # 训练1个GPU和每个GPU 8个图像。 我们可以在每个上放置多个图像
    # GPU，因为图像很小。 批量大小为8(GPUs * images/GPU)。
    GPU_COUNT = 1
    IMAGES_PER_GPU = 8

    # Number of classes (including background)
    # 类别数量（包括背景）
    NUM_CLASSES = 1 + 10  # background + 0~9 shapes

    # Use small images for faster training. Set the limits of the small side
    # 使用小图像进行更快速的训练。 设置小方面的限制
    # the large side, and that determines the image shape.
    # 大的一面，这决定了图像的形状。
    IMAGE_MIN_DIM = 128
    IMAGE_MAX_DIM = 128

    # IMAGE_SHAPE=[128,128,1] # 这样修改通道数没有效果，需进入`config.py` 去修改才行

    # Use smaller anchors because our image and objects are small
    # 使用较小的锚点是因为我们的图像和对象很小
    RPN_ANCHOR_SCALES = (8, 16, 32, 64, 128)  # anchor side in pixels

    # Reduce training ROIs per image because the images are small and have
    # 由于图像很小，因此减少了每个图像的训练ROI
    # few objects. Aim to allow ROI sampling to pick 33% positive ROIs.
    # 几件物品。 旨在允许ROI采样选择33％的正面投资回报率。
    TRAIN_ROIS_PER_IMAGE = 32

    # Use a small epoch since the data is simple
    # 因为数据很简单，所以使用一个epoch
    STEPS_PER_EPOCH = 100

    # use small validation steps since the epoch is small
    # 由于epoch 很小，因此使用小的验证步骤
    VALIDATION_STEPS = 5


config = ShapesConfig()
config.display()


def get_ax(rows=1, cols=1, size=8):
    """Return a Matplotlib Axes array to be used in
    all visualizations in the notebook. Provide a
    central point to control graph sizes.

    Change the default size attribute to control the size
    of rendered images
    返回要用于的Matplotlib轴数组
     笔记本中的所有可视化。 提供一个
     控制图形大小的中心点。

     更改默认大小属性以控制大小
     的渲染图像
    """
    _, ax = plt.subplots(rows, cols, figsize=(size * cols, size * rows))
    return ax


class ShapesDataset(utils.Dataset):
    """Generates the shapes synthetic dataset. The dataset consists of simple
    shapes (triangles, squares, circles) placed randomly on a blank surface.
    The images are generated on the fly. No file access required.
    生成形状合成数据集。 数据集由简单组成
     随机放置在空白表面上的形状（三角形，正方形，圆形）。
     图像即时生成。 无需文件访问。
    """

    def load_shapes(self, count, height, width):
        """Generate the requested number of synthetic images. 生成所需数量的合成图像。
        count: number of images to generate. 数量
        height, width: the size of the generated images. 尺寸
        """
        # Add classes 添加类别
        # self.add_class("shapes", 1, "square")
        # self.add_class("shapes", 2, "circle")
        # self.add_class("shapes", 3, "triangle")
        # self.add_class("shapes", 0, 'BG') # 标签0默认为背景
        label=['zero','one','two','three','four','five','six','seven','eight','nine']

        [self.add_class("shapes", i+1, label[i]) for i in range(10)] # 0~9 对应标签1~10  ；标签0默认为背景

        # Add images
        # Generate random specifications of images (i.e. color and
        # list of shapes sizes and locations). This is more compact than
        # actual images. Images are generated on the fly in load_image().
        # 生成图像的随机规格（即颜色和形状大小和位置列表）。 这比较紧凑比实际图片。图像在load_image（）中即时生成。
        for i in range(count):
            comb_image, mask, class_ids=self.random_comb(mnist,height,width)

            # 输入图片默认是3波段的
            comb_images=np.zeros([height,width,3],np.float32)
            comb_images[:,:,0]=comb_image
            comb_images[:, :, 1] = comb_image
            comb_images[:, :, 2] = comb_image
            comb_image=comb_images # [128,128,3]  转成3波段
            mask=np.asarray(mask).transpose([1, 2, 0]) # mask shape [128,128,16]
            self.add_image("shapes", image_id=i, path=None,
                           width=width, height=height,
                           image=comb_image,mask=mask,class_ids=class_ids)

    def load_image(self, image_id):
        """Generate an image from the specs of the given image ID.
        Typically this function loads the image from a file, but
        in this case it generates the image on the fly from the
        specs in image_info.
        """
        '''
        info = self.image_info[image_id]
        bg_color = np.array(info['bg_color']).reshape([1, 1, 3])
        image = np.ones([info['height'], info['width'], 3], dtype=np.uint8)
        image = image * bg_color.astype(np.uint8)
        for shape, color, dims in info['shapes']:
            image = self.draw_shape(image, shape, dims, color)
        '''
        info = self.image_info[image_id]
        image=info['image']
        return image

    def image_reference(self, image_id):
        """Return the shapes data of the image."""
        info = self.image_info[image_id]
        if info["source"] == "shapes":
            return info["shapes"]
        else:
            super(self.__class__).image_reference(self, image_id)

    def load_mask(self, image_id):
        """Generate instance masks for shapes of the given image ID.
        掩膜与类名对应起来
        """
        '''
        info = self.image_info[image_id]
        shapes = info['shapes']
        count = len(shapes)
        mask = np.zeros([info['height'], info['width'], count], dtype=np.uint8)
        for i, (shape, _, dims) in enumerate(info['shapes']):
            mask[:, :, i:i+1] = self.draw_shape(mask[:, :, i:i+1].copy(),
                                                shape, dims, 1) # 1 即color=1（形状内的像素值为1） 得到的掩膜为0、1组成的图片，大小和原始图片一样
        # Handle occlusions
        occlusion = np.logical_not(mask[:, :, -1]).astype(np.uint8)
        for i in range(count-2, -1, -1):
            mask[:, :, i] = mask[:, :, i] * occlusion
            occlusion = np.logical_and(occlusion, np.logical_not(mask[:, :, i]))
        # Map class names to class IDs.
        class_ids = np.array([self.class_names.index(s[0]) for s in shapes]) # 类名
        '''
        info = self.image_info[image_id]
        mask=info['mask']
        class_ids=info['class_ids']
        return mask, class_ids.astype(np.int32)

    def Image_Processing(self,image):
        '''缩放到32x32，像素值转成0、1'''
        image = np.reshape(image, [28, 28])  # [28,28]
        img = cv2.resize(image, (32, 32))  # [32,32]

        img_mask = np.round(img)  # 转成对应的掩膜
        return img, img_mask

    def random_comb(self,mnist,height,width):
        num_images = mnist.train.num_examples
        indexs = random.choices(np.arange(0, num_images), k=16)  # 随机选择16个索引值
        indexs = np.asarray(indexs, np.uint8).reshape([4, 4])
        class_ids = mnist.train.labels[indexs.flatten()]+1 # 0~9数字对应标签1~10,0默认为背景
        # comb_image = np.zeros([32 * 4, 32 * 4], np.float32)
        comb_image = np.zeros([height, width], np.float32)
        mask = []
        for i in range(4):
            for j in range(4):
                # image_mask = np.zeros([32 * 4, 32 * 4], np.uint8)
                image_mask = np.zeros([height, width], np.uint8)
                img_data = mnist.train.images[indexs[i, j]]
                img, img_mask = self.Image_Processing(img_data)
                comb_image[i * 32:(i + 1) * 32, j * 32:(j + 1) * 32] = img
                image_mask[i * 32:(i + 1) * 32, j * 32:(j + 1) * 32] = img_mask
                mask.append(image_mask)

        return comb_image, mask, class_ids

# Training dataset
dataset_train = ShapesDataset()
dataset_train.load_shapes(500, config.IMAGE_SHAPE[0], config.IMAGE_SHAPE[1])
dataset_train.prepare()

# Validation dataset
dataset_val = ShapesDataset()
dataset_val.load_shapes(50, config.IMAGE_SHAPE[0], config.IMAGE_SHAPE[1])
dataset_val.prepare()


# Load and display random samples
image_ids = np.random.choice(dataset_train.image_ids, 4)
for image_id in image_ids:
    image = dataset_train.load_image(image_id)
    mask, class_ids = dataset_train.load_mask(image_id)
    '''
    print(class_ids)
    plt.subplot(2,2,1)
    plt.imshow(image,'gray')
    plt.subplot(222)
    plt.imshow(mask[:,:,0], 'gray')
    plt.subplot(223)
    plt.imshow(mask[:, :, 6], 'gray')
    plt.subplot(224)
    plt.imshow(mask[:, :, 10], 'gray')
    plt.show()
    exit(-1)
    '''
    visualize.display_top_masks(image, mask, class_ids, dataset_train.class_names)


# Create model in training mode
model = modellib.MaskRCNN(mode="training", config=config,
                          model_dir=MODEL_DIR)

# Which weights to start with?
init_with = "coco"  # imagenet, coco, or last

if init_with == "imagenet":
    model.load_weights(model.get_imagenet_weights(), by_name=True)
elif init_with == "coco":
    # Load weights trained on MS COCO, but skip layers that
    # are different due to the different number of classes
    # See README for instructions to download the COCO weights
    model.load_weights(COCO_MODEL_PATH, by_name=True,
                       exclude=["mrcnn_class_logits", "mrcnn_bbox_fc",
                                "mrcnn_bbox", "mrcnn_mask"])
elif init_with == "last":
    # Load the last model you trained and continue training
    model.load_weights(model.find_last()[1], by_name=True)


# Train the head branches
# Passing layers="heads" freezes all layers except the head
# layers. You can also pass a regular expression to select
# which layers to train by name pattern.
# '''
model.train(dataset_train, dataset_val,
            learning_rate=config.LEARNING_RATE,
            epochs=1,
            layers='heads')
'''

# Fine tune all layers
# Passing layers="all" trains all layers. You can also
# pass a regular expression to select which layers to
# train by name pattern.
model.train(dataset_train, dataset_val,
            learning_rate=config.LEARNING_RATE / 10,
            epochs=2,
            layers="all")
'''

# Save weights
# Typically not needed because callbacks save after every epoch
# Uncomment to save manually
'''
保存重量
＃通常不需要，因为回调在每个epoch后都会保存
＃取消注释以手动保存
'''
# model_path = os.path.join(MODEL_DIR, "mask_rcnn_shapes.h5")
# model.keras_model.save_weights(model_path)


class InferenceConfig(ShapesConfig):
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1

inference_config = InferenceConfig()

# Recreate the model in inference mode
model = modellib.MaskRCNN(mode="inference",
                          config=inference_config,
                          model_dir=MODEL_DIR)

# Get path to saved weights
# Either set a specific path or find last trained weights
# model_path = os.path.join(ROOT_DIR, ".h5 file name here")
model_path = model.find_last()[1]

# Load trained weights (fill in path to trained weights here)
assert model_path != "", "Provide path to trained weights"
print("Loading weights from ", model_path)
model.load_weights(model_path, by_name=True)


# Test on a random image
image_id = random.choice(dataset_val.image_ids)
original_image, image_meta, gt_class_id, gt_bbox, gt_mask =\
    modellib.load_image_gt(dataset_val, inference_config,
                           image_id, use_mini_mask=False)

log("original_image", original_image)
log("image_meta", image_meta)
log("gt_class_id", gt_class_id)
log("gt_bbox", gt_bbox)
log("gt_mask", gt_mask)

visualize.display_instances(original_image, gt_bbox, gt_mask, gt_class_id,
                            dataset_train.class_names, figsize=(8, 8))


results = model.detect([original_image], verbose=1)

r = results[0]
visualize.display_instances(original_image, r['rois'], r['masks'], r['class_ids'],
                            dataset_val.class_names, r['scores'], ax=get_ax())

# Compute VOC-Style mAP @ IoU=0.5
# Running on 10 images. Increase for better accuracy.
image_ids = np.random.choice(dataset_val.image_ids, 10)
APs = []
for image_id in image_ids:
    # Load image and ground truth data
    image, image_meta, gt_class_id, gt_bbox, gt_mask = \
        modellib.load_image_gt(dataset_val, inference_config,
                               image_id, use_mini_mask=False)
    molded_images = np.expand_dims(modellib.mold_image(image, inference_config), 0)
    # Run object detection
    results = model.detect([image], verbose=0)
    r = results[0]
    # Compute AP
    AP, precisions, recalls, overlaps = \
        utils.compute_ap(gt_bbox, gt_class_id, gt_mask,
                         r["rois"], r["class_ids"], r["scores"], r['masks'])
    APs.append(AP)

print("mAP: ", np.mean(APs))