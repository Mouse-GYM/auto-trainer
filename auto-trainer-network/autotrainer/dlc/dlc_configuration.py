import logging
import os

import numpy

logger = logging.getLogger(__name__)


class DLCConfiguration:
    BODY_PARTS_KEY = 'bodyparts'
    PROJECT_PATH_KEY = 'project_path'
    TRAINING_FRACTION_KEY = 'TrainingFraction'
    SNAPSHOT_INDEX_KEY = 'snapshotindex'
    INIT_WEIGHTS_KEY = 'init_weights'
    BATCH_SIZE_KEY = 'batch_size'

    DEFAULT_BODY_PART_CATEGORY = 'default'

    def __init__(self, shuffle_index=1, training_index=0):
        self._sys_configuration = None
        self._body_parts = list()
        self._body_part_categories = list()
        self._body_parts_by_category = dict()
        self._shuffle_index = shuffle_index
        self._training_index = training_index
        self._training_fraction = 0.0
        self._model_folder = ""
        self._snapshots = None

        self._model_configuration = None
        self._model_batch_size = 1
        self._model_session = None
        self._model_inputs = None
        self._model_outputs = None

        self._predict = None

    @property
    def body_parts(self):
        return self._body_parts

    @property
    def body_part_categories(self):
        return self._body_part_categories

    def load_configuration(self, configuration_file, shuffle_index=None, training_index=None, batch_size=None):
        from deeplabcut.pose_estimation_tensorflow.config import load_config
        from deeplabcut.pose_estimation_tensorflow.core import predict
        from deeplabcut.utils import auxiliaryfunctions

        self._predict = predict

        if shuffle_index is not None:
            self._shuffle_index = shuffle_index

        if batch_size is not None:
            self._model_batch_size = batch_size

        if training_index is not None:
            self._training_index = training_index

        self._sys_configuration = auxiliaryfunctions.read_config(configuration_file)

        logger.debug(f"using {configuration_file}")

        cfg_body_parts = self._sys_configuration[self.BODY_PARTS_KEY]

        if isinstance(cfg_body_parts, dict):
            for cat in cfg_body_parts.keys():
                self._body_part_categories.append(cat)
                self._body_parts_by_category[cat] = list()

            for cat in self._body_part_categories:
                for part in cfg_body_parts[cat]:
                    self._body_parts.append(part)
                    self._body_parts_by_category[cat].append(part)
        elif isinstance(cfg_body_parts, list):
            self._body_parts_by_category[self.DEFAULT_BODY_PART_CATEGORY] = list()
            for part in cfg_body_parts:
                self._body_parts.append(part)
                self._body_parts_by_category[self.DEFAULT_BODY_PART_CATEGORY].append(part)

        logger.debug(f"loaded {len(self._body_parts)} body parts")

        self._training_fraction = self._sys_configuration[self.TRAINING_FRACTION_KEY][self._training_index]

        self._model_folder = os.path.join(self._sys_configuration[self.PROJECT_PATH_KEY],
                                          str(auxiliaryfunctions.get_model_folder(self._training_fraction,
                                                                                  self._shuffle_index,
                                                                                  self._sys_configuration)))

        model_configuration_path = os.path.join(self._model_folder, "test", "pose_cfg.yaml")

        logger.debug(f"using pose configuration {model_configuration_path}")

        try:
            self._model_configuration = load_config(model_configuration_path)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Model for shuffle {self._shuffle_index} and train fraction {self._training_fraction} does not exist.")

        try:
            self._snapshots = numpy.array(
                [fn.split('.')[0] for fn in os.listdir(os.path.join(self._model_folder, "train")) if "index" in fn])
        except FileNotFoundError:
            raise FileNotFoundError(
                f"The dataset for shuffle {self._shuffle_index} has not been trained or does not exist.\n Please "
                f"train it before using it to analyze videos.\n Use the function 'train_network' to train the network "
                f"for this shuffle.")

        snapshot_index = self._sys_configuration[self.SNAPSHOT_INDEX_KEY]
        increasing_indices = numpy.argsort([int(m.split('-')[1]) for m in self._snapshots])
        self._snapshots = self._snapshots[increasing_indices]
        logger.info(f"using {self._snapshots[snapshot_index]} for {self._model_folder}")

        self._model_configuration[self.INIT_WEIGHTS_KEY] = os.path.join(self._model_folder, 'train',
                                                                        self._snapshots[snapshot_index])

        self._model_configuration[self.BATCH_SIZE_KEY] = self._model_batch_size

        self._model_session, self._model_inputs, self._model_outputs = predict.setup_pose_prediction(
            self._model_configuration)

    def predict(self, frames):
        return self._predict.getposeNP(frames, self._model_configuration, self._model_session, self._model_inputs,
                                       self._model_outputs)
