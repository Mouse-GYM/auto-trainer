from autotrainer.inference import PoseAlgorithm


class PelletPoseAlgorithm(PoseAlgorithm):
    def __init__(self):
        super().__init__()
        self._pellet_part_index = -1
        self._star_part_index = -1
        self._api_status_token = None
        self._pellet_delivery_status = 0
        self._pellet_history = 0

    '''
    Will be called once after the model initialized and body parts properties have been set.
    See part_names() and get_part_index(name)
    '''

    def initialize(self):
        self._pellet_part_index = self.get_part_index("Pellet")
        self._star_part_index = self.get_part_index("Star")

    '''
    all_frames - frames in order as output from DLC
    left_frames - sorted for just the left
    right_frames - sorted for just the right
    Each frame is already reshaped to (num_body_parts, 3)
    '''

    def process_frames(self, all_frames: list, left_frames: list, right_frames: list):
        if self._star_part_index == -1 or self._pellet_part_index == -1:
            return (0, 0, 0, 0), (0, 0, 0, 0)

        pellet1, star1 = self.find_parts(left_frames)
        pellet2, star2 = self.find_parts(right_frames)

        pellet_seen = False

        for pose in all_frames:
            pellet_seen = pose[self._pellet_part_index, 2] >= 0.9
            if pellet_seen:
                break

        if self._api_status_token is None:
            if pellet_seen:
                self._pellet_history = 0
            else:
                self._pellet_history += 1
            if self._pellet_delivery_status == 3:
                self._pellet_delivery_status = 0
                self._pellet_history = 0
            elif self._pellet_delivery_status == 2:
                self._api_status_token = self.api.release_pellet()
                self._pellet_delivery_status = 3
            elif self._pellet_delivery_status == 1:
                self._api_status_token = self.api.send_pellet()
                self._pellet_delivery_status = 2
            elif self._pellet_delivery_status == 0:
                if self._pellet_history >= 10:
                    self._api_status_token = self.api.load_pellet()
                    self._pellet_delivery_status = 1
        # API supports these commands.
        # self.api.move_home()
        # self.api.load_pellet()
        # self.api.send_pellet()
        # self.api.release_pellet()
        # Can return up to two locations per camera to be shown on the live feed
        return (*pellet1, *star1), (*pellet2, *star2)

    def api_response(self, token: object, success: bool):
        # The token is an opaque object.  Should just use with != or == to determine if it one you are waiting for.
        # If we get our token back, the move is done.  Clear our flag.
        if token == self._api_status_token:
            self._api_status_token = None

    def terminate(self):
        pass

    def find_parts(self, frames: list) -> ((float, float), (float, float)):
        pellet = (0, 0)
        star = (0, 0)
        for pose in frames:
            if pose[self._pellet_part_index, 2] >= 0.9:
                pellet = pose[self._pellet_part_index, 0:2]
            if pose[self._star_part_index, 2] >= 0.9:
                star = pose[self._star_part_index, 0:2]
        return pellet, star
