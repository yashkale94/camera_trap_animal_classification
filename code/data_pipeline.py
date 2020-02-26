#!python
# -*- coding: utf-8 -*-

"""
Contains the code to build the Data Input Pipeline for TensorFlow models.

"""
import numpy as np
import pandas as pd
import tensorflow as tf


class PipelineGenerator(object):
    """
    Creates a pipeline with the required configuration and image 
    transformations. Takes as input a CSV file which lists the images that needs
    to be loaded and transformed.
    
    NOTE: The dataset must have paths of the images in the sequences stored in 
          columns with names starting from 'image1', 'image2', and so on.
    
    Parameters:
    -----------
    dataset_file: Path to the CSV file containing the list of images and labels.
    
    images_dir: Path to the directory containing the images to be loaded.
    
    sequence_image_count: The number of images in each sequence. Default is 3.
    
    label_name: Name of the column in the CSV file corresponding to the label.
                Default is 'has_animal'.
                
    mode: The string representing the mode in which the data needs to be loaded. 
          For possible modes and definitions, check the 'Attributes' section. 
          Default is MODE_ALL.
          
    image_size: Specifies the size of the input images. Must be provided as a 
                tuple of integers specifying width and height. Default is 
                (224, 224).
          
    image_idx: Used when the selected mode is MODE_SINGLE. Specifies the index 
               of the image that needs to be picked. Must be > 0 and 
               <= sequence_image_count. Default is 1.

    resize: Specifies the size to which the images must be resized. Default is
            None. Must be provided as a tuple of integers specifying width and
            height. If None, no resizing is done.

    perform_shuffle: Specify if the dataset needs to be shuffled. Default: True.

    shuffle_buffer_size: Specifies the buffer size to use to shuffle the CSV
                         records. Check tensorflow.data.Dataset.shuffle() 
                         documentation for more details. Default is 10000.

    kwargs: Any additional keywords argument that needs to be passed to the 
            make_csv_dataset function of TensorFlow.
            
    Attributes:
    -----------
    MODE_ALL: Configuration to make the pipeline return all the images in a 
              dictionary with key as the original column name.
    
    MODE_FLAT_ALL: Configuration to make the pipeline returns all the images of 
                   the sequence one by one.
    
    MODE_SINGLE: Configuration to make the pipeline return only the selected 
                 image from the sequence. Choice of image is specified by the 
                 parameter `image_idx`.
                 
    MODE_SEQUENCE: Configuration to make the pipeline return the sequence of 
                   images as a tensor (array) with a single label.
                   
    MODE_MASK_MOG2: 
            
    """
    
    MODE_ALL = "mode_all"
    MODE_FLAT_ALL = "mode_flat_all"
    MODE_SINGLE = "mode_single"
    MODE_SEQUENCE = "mode_sequence"
    
    
    def __init__(self, dataset_file, images_dir, sequence_image_count=3,
                 label_name='has_animal', mode=MODE_ALL, image_size=(224, 224),
                 image_idx=1, resize=None, is_training=True,
                 shuffle_buffer_size=10000, **kwargs):
        self._modes = [self.MODE_ALL, self.MODE_FLAT_ALL, self.MODE_SINGLE, 
                       self.MODE_SEQUENCE]
        self._dataset_file = dataset_file
        self._images_dir = images_dir
        self._sequence_image_count = sequence_image_count
        self._label_name = label_name
        self._mode = mode
        self._image_size = image_size
        self._image_idx = image_idx
        self._resize = resize
        self._is_training = is_training
        self._shuffle_buffer_size = shuffle_buffer_size
        self._kwargs = kwargs
        self._AUTOTUNE = tf.data.experimental.AUTOTUNE
        self._size = None

        if self._mode not in self._modes:
            raise ValueError("Invalid mode. Please select one from {}."\
                             .format(self._modes))
        
        if (self._mode == self.MODE_SINGLE and 
            (self._image_idx <= 0 or 
             self._image_idx > self._sequence_image_count)):
            raise IndexError("Image index is out of bounds.")
        
        if self._resize:
            self._image_size = self._resize
        
        if self._mode == self.MODE_ALL:
            self._parse_data = self._parse_data_all
        elif self._mode == self.MODE_FLAT_ALL:
            self._parse_data = self._parse_data_flat
        elif self._mode == self.MODE_SEQUENCE:
            self._parse_data = self._parse_data_sequence
        else:
            self._parse_data = self._parse_data_single


    def _augment_img(self, img, seed):
        
        def flip(x):
            """Flip augmentation

            Args:
                x: Image to flip

            Returns:
                x: Augmented image
            """
            x = tf.image.random_flip_left_right(x, seed=seed)
            return x

        def color(x):
            """Color augmentation

            Args:
                x: Image

            Returns:
                x: Augmented image
            """
            x = tf.image.random_hue(x, 0.08, seed=seed)
            x = tf.image.random_saturation(x, 0.6, 1.6, seed=seed)
            x = tf.image.random_brightness(x, 0.05, seed=seed)
            x = tf.image.random_contrast(x, 0.7, 1.3, seed=seed)
            return x
        
        def zoom(x):
            """Zoom augmentation

            Args:
                x: Image

            Returns:
                x: Augmented image
            """
            # Generate 10 crop settings, ranging from a 1% to 10% crop.
            scales = list(np.arange(0.9, 1.0, 0.02))
            scale = scales[seed % len(scales)]
            
            x1 = y1 = 0.5 - (0.5 * scale)
            x2 = y2 = 0.5 + (0.5 * scale)
            boxes = [x1, y1, x2, y2]
            
            # Create different crops for an image
            x = tf.image.crop_and_resize([img], boxes=[boxes], 
                                         box_indices=[0], 
                                         crop_size=self._image_size)
            
            # Squeeze out the final dimension
            x = tf.squeeze(x)
            
            return x

        # Augment images only in training mode.
        if not self._is_training:
            return img

        img = flip(img)

        if seed < 500:
            img = color(img)
        
        if seed >= 250 and seed < 750:
            img = zoom(img)
        
        return tf.clip_by_value(img, 0, 1)
    
    
    def _decode_img(self, img):
        # Convert the compressed string to a 3D uint8 tensor
        img = tf.image.decode_jpeg(img, channels=3)

        # Use `convert_image_dtype` to convert to floats in the [0,1] range.
        img = tf.image.convert_image_dtype(img, tf.float32)

        # Resize the image to the desired size if needed.
        if self._resize:
            img = tf.image.resize(img, list(self._resize), name="resize-input")

        return img
    
    
    def _parse_data_all(self, metadata, label):
        data_point = {}
        seed = np.random.randint(1000)
        
        # Read each image and add to dictionary
        for img_num in range(1, self._sequence_image_count + 1):
            img_name = "image" + str(img_num)
            img = tf.io.read_file(tf.strings.join([
                self._images_dir, metadata[img_name]]))
            img = self._decode_img(img)
            img = self._augment_img(img, seed)
            data_point[img_name] = img

        return data_point, label
    
    
    def _parse_data_single(self, metadata, label):
        img = tf.io.read_file(tf.strings.join([
                self._images_dir, metadata["image" + str(self._image_idx)]]))
        img = self._decode_img(img)
        
        seed = np.random.randint(1000)
        img = self._augment_img(img, seed)
        return img, label


    def _parse_data_flat(self, metadata, label):
        images, labels = [], []
        seed = np.random.randint(1000)
        
        # Read each image and add to list
        for img_num in range(1, self._sequence_image_count + 1):
            img = tf.io.read_file(tf.strings.join([
                self._images_dir, metadata["image" + str(img_num)]]))
            img = self._decode_img(img)
            img = self._augment_img(img, seed)
            images.append(img)
            labels.append(label)
        
        return tf.data.Dataset.from_tensor_slices((images, labels))
    
    
    def _parse_data_sequence(self, metadata, label):
        images = []
        seed = np.random.randint(1000)
        
        # Read each image and add to list
        for img_num in range(1, self._sequence_image_count + 1):
            img = tf.io.read_file(tf.strings.join([
                self._images_dir, metadata["image" + str(img_num)]]))
            img = self._decode_img(img)
            img = self._augment_img(img, seed)
            images.append(img)
        
        return tf.convert_to_tensor(images), label


    def get_size(self):
        if self._size is None:
            print("Size cannot be determined before the 'get_pipeline' function call. Returning None.")
        return self._size


    def get_pipeline(self):
        """
        Returns a pipeline that was constructed using the parameters specified.
        
        Returns:
        --------
        dataset_images: A tensorflow.data.Dataset pipeline object.
        
        """
        # Create a dataset with records from the CSV file.
        data_csv = pd.read_csv(self._dataset_file)

        # Set the size attribute.
        self._size = len(data_csv)
        if self._mode == self.MODE_FLAT_ALL:
            self._size = self._size * self._sequence_image_count

        image_col_names = ["image" + str(img_num) for img_num in range(1, self._sequence_image_count + 1)]
        file_paths = data_csv[image_col_names]
        labels = data_csv[[self._label_name]]
        dataset_files = tf.data.Dataset.from_tensor_slices((file_paths.to_dict('list'), labels.values.reshape(-1, )))

        # Parse the data and load the images.
        if self._mode == self.MODE_FLAT_ALL:
            dataset_images = dataset_files.flat_map(self._parse_data)
        else:
            dataset_images = dataset_files.map(self._parse_data, num_parallel_calls=self._AUTOTUNE)

        if self._is_training:
            dataset_images = dataset_images.shuffle(buffer_size=self._shuffle_buffer_size, reshuffle_each_iteration=True)
            dataset_images = dataset_images.repeat()
            print("Note: The dataset is being prepared for training mode. "
                  "It has been shuffled, and repeated indefinitely.")

        return dataset_images
