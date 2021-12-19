import sys,os,json

import numpy as np
from PIL import Image

import torch
import torch.utils.data as data

if sys.version_info[0] == 2:
    import xml.etree.cElementTree as ET
else:
    import xml.etree.ElementTree as ET

from utils.utils import *

class KAISTPed(data.Dataset):
    """KAIST Detection Dataset Object
    input is image, target is annotation
    Arguments:
        root (string): filepath to VOCdevkit folder.
        image_set (string): imageset to use (eg. 'train', 'val', 'test')
        transform (callable, optional): transformation to perform on the
            input image
        target_transform (callable, optional): transformation to perform on the
            target `annotation`
            (eg: take in caption string, return tensor of word indices)
        dataset_name (string, optional): which dataset to load
            (default: 'KAIST')
        condition (string, optional): load condition
            (default: 'Reasonabel')
    """
    def __init__(self, args, condition='train'):
        self.args = args
        assert condition in args.dataset.OBJ_LOAD_CONDITIONS
        
        self.mode = condition
        self.image_set = args[condition].img_set
        self.img_transform = args[condition].img_transform
        self.co_transform = args[condition].co_transform        
        self.cond = args.dataset.OBJ_LOAD_CONDITIONS[condition]
        self.annotation = args[condition].annotation
        self._parser = LoadBox()        

        self._annopath = os.path.join('%s', 'annotations_paired', '%s', '%s', '%s', '%s.txt')

        self._imgpath = os.path.join('%s', 'images', '%s', '%s', '%s', '%s.jpg')  
        
        self.ids = list()
        for line in open(os.path.join('./imageSets', self.image_set)):
            self.ids.append((self.args.path.DB_ROOT, line.strip().split('/')))

    def __str__(self):
        return self.__class__.__name__ + '_' + self.image_set

    def __getitem__(self, index): 

        vis, lwir, boxes, labels = self.pull_item(index)
        return vis, lwir, boxes, labels, torch.ones(1,dtype=torch.int)*index  

    def pull_item(self, index):
        
        frame_id = self.ids[index]
        set_id, vid_id, img_id = frame_id[-1]

        vis = Image.open( self._imgpath % ( *frame_id[:-1], set_id, vid_id, 'visible', img_id ))
        lwir = Image.open( self._imgpath % ( *frame_id[:-1], set_id, vid_id, 'lwir', img_id ) ).convert('L')
    
        width, height = lwir.size

        # paired annotation
        if self.mode == 'train': 
            vis_boxes = list()
            lwir_boxes = list()

            for line in open(self._annopath % ( *frame_id[:-1], set_id, vid_id, 'visible', img_id )) :
                vis_boxes.append(line.strip().split(' '))
            for line in open(self._annopath % ( *frame_id[:-1], set_id, vid_id, 'lwir', img_id)) :
                lwir_boxes.append(line.strip().split(' '))
        
            vis_boxes = vis_boxes[1:]
            lwir_boxes = lwir_boxes[1:]

            boxes_vis = [[0, 0, 0, 0, -1]]
            boxes_lwir = [[0, 0, 0, 0, -1]]

            for i in range(len(vis_boxes)) :
                name = vis_boxes[i][0]
                bndbox = [int(i) for i in vis_boxes[i][1:5]]
                bndbox[2] = min( bndbox[2] + bndbox[0], width )
                bndbox[3] = min( bndbox[3] + bndbox[1], height )
                bndbox = [ cur_pt / width if i % 2 == 0 else cur_pt / height for i, cur_pt in enumerate(bndbox) ]
                bndbox.append(1)
                boxes_vis += [bndbox]

            for i in range(len(lwir_boxes)) :
                name = lwir_boxes[i][0]
                bndbox = [int(i) for i in lwir_boxes[i][1:5]]
                bndbox[2] = min( bndbox[2] + bndbox[0], width )
                bndbox[3] = min( bndbox[3] + bndbox[1], height )
                bndbox = [ cur_pt / width if i % 2 == 0 else cur_pt / height for i, cur_pt in enumerate(bndbox) ]
                bndbox.append(1)
                boxes_lwir += [bndbox]

            boxes_vis = np.array(boxes_vis, dtype=np.float)
            boxes_lwir = np.array(boxes_lwir, dtype=np.float)

        else :
            boxes_vis = [[0, 0, 0, 0, -1]]
            boxes_lwir = [[0, 0, 0, 0, -1]]
            boxes_vis = np.array(boxes_vis, dtype=np.float)
            boxes_lwir = np.array(boxes_lwir, dtype=np.float)

        ## Apply transforms
        if self.img_transform is not None:
            vis, lwir, boxes_vis , boxes_lwir, _ = self.img_transform(vis, lwir, boxes_vis, boxes_lwir)

        if self.co_transform is not None:
            
            pair = 1

            vis, lwir, boxes_vis, boxes_lwir, pair = self.co_transform(vis, lwir, boxes_vis, boxes_lwir, pair)                      
            
            if boxes_vis is None:
                boxes = boxes_lwir
            elif boxes_lwir is None:
                boxes = boxes_vis
            else : 

                ## Pair Condition
                ## RGB / Thermal
                ##  1  /  0  = 1
                ##  0  /  1  = 2
                ##  1  /  1  = 3

                if pair == 1 :
                    
                    if len(boxes_vis.shape) != 1 :
                        boxes_vis[1:,4] = 3
                    if len(boxes_lwir.shape) != 1 :
                        boxes_lwir[1:,4] = 3
                else : 
                    if len(boxes_vis.shape) != 1 :
                        boxes_vis[1:,4] = 1
                    if len(boxes_lwir.shape) != 1 :
                        boxes_lwir[1:,4] = 2
                
                boxes = torch.cat((boxes_vis,boxes_lwir), dim=0)
                boxes = torch.tensor(list(map(list,set([tuple(bb) for bb in boxes.numpy()]))))   

        ## Set ignore flags
        ignore = torch.zeros( boxes.size(0), dtype=torch.bool)
               
        for ii, box in enumerate(boxes):
                        
            x = box[0] * width
            y = box[1] * height
            w = ( box[2] - box[0] ) * width
            h = ( box[3] - box[1] ) * height

            if  x < self.cond['xRng'][0] or \
                y < self.cond['xRng'][0] or \
                x+w > self.cond['xRng'][1] or \
                y+h > self.cond['xRng'][1] or \
                w < self.cond['wRng'][0] or \
                w > self.cond['wRng'][1] or \
                h < self.cond['hRng'][0] or \
                h > self.cond['hRng'][1]:

                ignore[ii] = 1
        
        boxes[ignore, 4] = -1
        
        labels = boxes[:,4]
        boxes_t = boxes[:,0:4]     
        
        return vis, lwir, boxes_t, labels

    def __len__(self):
        return len(self.ids)

    def collate_fn(self, batch):
        """
        Since each image may have a different number of objects, we need a collate function (to be passed to the DataLoader).
        This describes how to combine these tensors of different sizes. We use lists.
        Note: this need not be defined in this Class, can be standalone.
        :param batch: an iterable of N sets from __getitem__()
        :return: a tensor of images, lists of varying-size tensors of bounding boxes, labels, and difficulties
        """

        vis = list()
        lwir = list()
        boxes = list()
        labels = list()
        index = list()

        for b in batch:
            vis.append(b[0])
            lwir.append(b[1])
            boxes.append(b[2])
            labels.append(b[3])
            index.append(b[4])

        vis = torch.stack(vis, dim=0)
        lwir = torch.stack(lwir, dim=0)
  
        return vis, lwir, boxes, labels, index  

class LoadBox(object):
    """Transforms a VOC annotation into a Tensor of bbox coords and label index
    Initilized with a dictionary lookup of classnames to indexes
    Arguments:
        class_to_ind (dict, optional): dictionary lookup of classnames -> indexes
            (default: alphabetic indexing of VOC's 20 classes)
        keep_difficult (bool, optional): keep difficult instances or not
            (default: False)
        height (int): height
        width (int): width
    """

    def __init__(self, bbs_format='xyxy'):
        assert bbs_format in ['xyxy', 'xywh']                
        self.bbs_format = bbs_format
        self.pts = ['x', 'y', 'w', 'h']

    def __call__(self, target, width, height):
        """
        Arguments:
            target (annotation) : the target annotation to be made usable
                will be an ET.Element
        Returns:
            a list containing lists of bounding boxes  [bbox coords, class name]
        """                
        res = [ [0, 0, 0, 0, -1] ]

        for obj in target.iter('object'):           
            name = obj.find('name').text.lower().strip()            
            bbox = obj.find('bndbox')
            bndbox = [ int(bbox.find(pt).text) for pt in self.pts ]

            if self.bbs_format in ['xyxy']:
                bndbox[2] = min( bndbox[2] + bndbox[0], width )
                bndbox[3] = min( bndbox[3] + bndbox[1], height )

            bndbox = [ cur_pt / width if i % 2 == 0 else cur_pt / height for i, cur_pt in enumerate(bndbox) ]
            
            bndbox.append(1)
            res += [bndbox]  # [xmin, ymin, xmax, ymax, label_ind, occ]
            
        return np.array(res, dtype=np.float)  # [[xmin, ymin, xmax, ymax, label_ind], ... ]


if __name__ == '__main__':
    """Debug KAISTPed class"""
    from matplotlib import patches
    from matplotlib import pyplot as plt
    from utils.functional import to_pil_image, unnormalize
    import config

    def draw_boxes(axes, boxes, labels, target_label, color):
        for x1, y1, x2, y2 in boxes[labels == target_label]:
            w, h = x2 - x1 + 1, y2 - y1 + 1
            axes[0].add_patch(patches.Rectangle((x1, y1), w, h, fill=False, edgecolor=color, lw=1))
            axes[1].add_patch(patches.Rectangle((x1, y1), w, h, fill=False, edgecolor=color, lw=1))

    args = config.args
    test = config.test

    fig, axes = plt.subplots(1, 2, figsize=(15, 10))

    dataset = KAISTPed(args, condition='test')

    # HACK(sohwang): KAISTPed always returns empty boxes in test mode
    dataset.mode = 'train'

    vis, lwir, boxes, labels, indices = dataset[1300]

    vis_mean = dataset.co_transform.transforms[-2].mean
    vis_std = dataset.co_transform.transforms[-2].std

    lwir_mean = dataset.co_transform.transforms[-1].mean
    lwir_std = dataset.co_transform.transforms[-1].std

    # C x H x W -> H X W x C
    vis_np = np.array(to_pil_image(unnormalize(vis, vis_mean, vis_std)))
    lwir_np = np.array(to_pil_image(unnormalize(lwir, lwir_mean, lwir_std)))

    # Draw images
    axes[0].imshow(vis_np)
    axes[1].imshow(lwir_np)
    axes[0].axis('off')
    axes[1].axis('off')

    # Draw boxes on images
    input_h, input_w = test.input_size
    xyxy_scaler_np = np.array([[input_w, input_h, input_w, input_h]], dtype=np.float32)
    boxes = boxes * xyxy_scaler_np

    draw_boxes(axes, boxes, labels, 3, 'blue')
    draw_boxes(axes, boxes, labels, 1, 'red')
    draw_boxes(axes, boxes, labels, 2, 'green')

    frame_id = dataset.ids[indices.item()]
    set_id, vid_id, img_id = frame_id[-1]
    fig.savefig(f'{set_id}_{vid_id}_{img_id}.png')
