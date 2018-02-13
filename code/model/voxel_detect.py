import os
from importlib import import_module
import numpy as np
import tensorflow as tf
import progressbar
import h5py
from .base_conv3 import base_conv3
from utils.iso_boxes import iso_cube
from utils.regu_grid import regu_grid


class voxel_detect(base_conv3):
    """ basic 3d detection based method
    """
    @staticmethod
    def get_trainer(args, new_log):
        from train.train_voxel_detect import train_voxel_detect
        return train_voxel_detect(args, new_log)

    def __init__(self, args):
        super(voxel_detect, self).__init__(args)
        self.batch_allot = getattr(
            import_module('model.batch_allot'),
            'batch_allot_vxhit'
        )
        self.num_appen = 4
        self.crop_size = 64
        self.hmap_size = 32

    def receive_data(self, thedata, args):
        """ Receive parameters specific to the data """
        super(voxel_detect, self).receive_data(thedata, args)
        self.out_dim = thedata.join_num

    def provider_worker(self, line, image_dir, caminfo):
        img_name, pose_raw = self.data_module.io.parse_line_annot(line)
        img = self.data_module.io.read_image(os.path.join(image_dir, img_name))
        pcnt, resce = self.data_module.ops.voxel_hit(
            img, pose_raw, caminfo.crop_size, caminfo)
        resce3 = resce[0:4]
        cube = iso_cube()
        cube.load(resce3)
        pose_pca = self.data_module.ops.raw_to_pca(pose_raw, resce3)
        vxhit = self.data_module.ops.raw_to_vxlabel(
            pose_raw, cube, self.hmap_size, caminfo
        )
        index = self.data_module.io.imagename2index(img_name)
        return (index, np.expand_dims(pcnt, axis=-1),
                pose_pca.flatten().T, vxhit, resce)

    def yanker(self, pose_local, resce):
        resce3 = resce[0:4]
        return self.data_module.ops.pca_to_raw(pose_local, resce3)

    def yanker_hmap(self, resce, voxhig, hmap_size, caminfo):
        resce3 = resce[0:4]
        cube = iso_cube()
        cube.load(resce3)
        return self.data_module.ops.vxlabel_to_raw(
            voxhig, cube, hmap_size, caminfo)

    @staticmethod
    def put_worker(
        args, image_dir, model_inst,
            caminfo, data_module, batchallot):
        bi = args[0]
        line = args[1]
        index, frame, poses, vxhit, resce = \
            model_inst.provider_worker(line, image_dir, caminfo)
        batchallot.batch_index[bi, :] = index
        batchallot.batch_frame[bi, ...] = frame
        batchallot.batch_poses[bi, :] = poses
        batchallot.batch_vxhit[bi, :] = vxhit
        batchallot.batch_resce[bi, :] = resce

    def write_pred(self, fanno, caminfo,
                   batch_index, batch_resce, batch_poses):
        for ii in range(batch_index.shape[0]):
            img_name = self.data_module.io.index2imagename(batch_index[ii, 0])
            resce = batch_resce[ii, :]
            vxhit = batch_poses[ii, ...]
            vxhit = np.argmax(vxhit, axis=0)
            pose_raw = self.yanker_hmap(
                resce, np.array(vxhit),
                self.hmap_size, caminfo)
            fanno.write(
                img_name +
                '\t' + '\t'.join("%.4f" % x for x in pose_raw.flatten()) +
                '\n')

    def fetch_batch(self, fetch_size=None):
        if fetch_size is None:
            fetch_size = self.batch_size
        batch_end = self.batch_beg + fetch_size
        if batch_end >= self.store_size:
            self.batch_beg = batch_end
            batch_end = self.batch_beg + fetch_size
            self.split_end -= self.store_size
        # print(self.batch_beg, batch_end, self.split_end)
        if batch_end >= self.split_end:
            return None
        self.batch_data = {
            'batch_index': self.store_file['index'][self.batch_beg:batch_end, ...],
            'batch_frame': self.store_file['frame'][self.batch_beg:batch_end, ...],
            'batch_poses': self.store_file['vxhit'][self.batch_beg:batch_end, ...].astype(np.int32),
            'batch_resce': self.store_file['resce'][self.batch_beg:batch_end, ...]
        }
        self.batch_beg = batch_end
        return self.batch_data

    def prepare_data(self, thedata, args,
                     batchallot, file_annot, name_appen):
        num_line = int(sum(1 for line in file_annot))
        file_annot.seek(0)
        batchallot.allot(num_line)
        store_size = batchallot.store_size
        num_stores = int(np.ceil(float(num_line) / store_size))
        self.logger.debug(
            'preparing data [{}]: {:d} lines (producing {:.4f} GB for store size {:d}) ...'.format(
                self.__class__.__name__, num_line,
                float(batchallot.store_bytes) / (2 << 30),
                store_size))
        timerbar = progressbar.ProgressBar(
            maxval=num_stores,
            widgets=[
                progressbar.Percentage(),
                ' ', progressbar.Bar('=', '[', ']'),
                ' ', progressbar.ETA()]
        ).start()
        crop_size = self.crop_size
        hmap_size = self.hmap_size
        out_dim = self.out_dim
        num_channel = self.num_channel
        num_appen = self.num_appen
        with h5py.File(os.path.join(self.prepare_dir, name_appen), 'w') as h5file:
            h5file.create_dataset(
                'index',
                (num_line, 1),
                compression='lzf',
                dtype=np.int32
            )
            h5file.create_dataset(
                'frame',
                (num_line,
                    crop_size, crop_size, crop_size,
                    num_channel),
                chunks=(1,
                        crop_size, crop_size, crop_size,
                        num_channel),
                compression='lzf',
                # dtype=np.float32)
                dtype=float)
            h5file.create_dataset(
                'poses',
                (num_line, out_dim * 3),
                compression='lzf',
                # dtype=np.float32)
                dtype=float)
            # h5file.create_dataset(
            #     'vxhit',
            #     (num_line, hmap_size, hmap_size, hmap_size, out_dim),
            #     compression='lzf',
            #     # dtype=np.float32)
            #     dtype=float)
            h5file.create_dataset(
                'vxhit',
                (num_line, out_dim),
                compression='lzf',
                # dtype=np.float32)
                dtype=float)
            h5file.create_dataset(
                'resce',
                (num_line, num_appen),
                compression='lzf',
                # dtype=np.float32)
                dtype=float)
            bi = 0
            store_beg = 0
            while True:
                resline = self.data_module.provider.puttensor_mt(
                    file_annot, self.put_worker, self.image_dir,
                    self, thedata, self.data_module, batchallot
                )
                if 0 > resline:
                    break
                h5file['index'][store_beg:store_beg + resline, ...] = \
                    batchallot.batch_index[0:resline, ...]
                h5file['frame'][store_beg:store_beg + resline, ...] = \
                    batchallot.batch_frame[0:resline, ...]
                h5file['poses'][store_beg:store_beg + resline, ...] = \
                    batchallot.batch_poses[0:resline, ...]
                h5file['vxhit'][store_beg:store_beg + resline, ...] = \
                    batchallot.batch_vxhit[0:resline, ...]
                h5file['resce'][store_beg:store_beg + resline, ...] = \
                    batchallot.batch_resce[0:resline, ...]
                timerbar.update(bi)
                bi += 1
                store_beg += resline
        timerbar.finish()

    def draw_random(self, thedata, args):
        import matplotlib.pyplot as mpplot
        from mpl_toolkits.mplot3d import Axes3D
        from mayavi import mlab

        with h5py.File(self.appen_train, 'r') as h5file:
            store_size = h5file['index'].shape[0]
            frame_id = np.random.choice(store_size)
            # frame_id = 651
            img_id = h5file['index'][frame_id, 0]
            frame_h5 = np.squeeze(h5file['frame'][frame_id, ...], -1)
            poses_h5 = h5file['poses'][frame_id, ...].reshape(-1, 3)
            vxhit_h5 = h5file['vxhit'][frame_id, ...]
            resce_h5 = h5file['resce'][frame_id, ...]

        print('[{}] drawing image #{:d} ...'.format(self.name_desc, img_id))
        print(np.min(frame_h5), np.max(frame_h5))
        print(np.histogram(frame_h5, range=(1e-4, np.max(frame_h5))))
        print(np.min(poses_h5, axis=0), np.max(poses_h5, axis=0))
        print(resce_h5)
        resce3 = resce_h5[0:4]
        cube = iso_cube()
        cube.load(resce3)
        cube.show_dims()
        img_name = args.data_io.index2imagename(img_id)
        img = args.data_io.read_image(os.path.join(self.image_dir, img_name))
        from colour import Color
        colors = [Color('orange').rgb, Color('red').rgb, Color('lime').rgb]
        fig, _ = mpplot.subplots(nrows=2, ncols=4, figsize=(2 * 5, 4 * 5))

        ax = mpplot.subplot(2, 4, 3, projection='3d')
        points3 = args.data_ops.img_to_raw(img, self.caminfo)
        points3_trans = cube.pick(points3)
        points3_trans = cube.transform_to_center(points3_trans)
        numpts = points3_trans.shape[0]
        if 1000 < numpts:
            points3_trans = points3_trans[
                np.random.choice(numpts, 1000, replace=False), :]
        ax.scatter(
            points3_trans[:, 0], points3_trans[:, 1], points3_trans[:, 2],
            color=Color('lightsteelblue').rgb)
        args.data_draw.draw_raw3d_pose(ax, thedata, poses_h5)
        corners = cube.transform_to_center(cube.get_corners())
        cube.draw_cube_wire(ax, corners)
        # ax.view_init(azim=-120, elev=-150)
        ax.view_init(azim=-90, elev=-75)

        ax = mpplot.subplot(2, 4, 1)
        ax.imshow(img, cmap='bone')
        pose_raw = self.yanker(poses_h5, resce_h5)
        args.data_draw.draw_pose2d(
            ax, thedata,
            args.data_ops.raw_to_2d(pose_raw, self.caminfo)
        )
        rects = cube.proj_rects_3(
            args.data_ops.raw_to_2d, self.caminfo
        )
        for ii, rect in enumerate(rects):
            rect.draw(ax, colors[ii])

        ax = mpplot.subplot(2, 4, 2, projection='3d')
        numpts = points3.shape[0]
        if 1000 < numpts:
            samid = np.random.choice(numpts, 1000, replace=False)
            points3_sam = points3[samid, :]
        else:
            points3_sam = points3
        ax.scatter(
            points3_sam[:, 0], points3_sam[:, 1], points3_sam[:, 2],
            color=Color('lightsteelblue').rgb)
        ax.view_init(azim=-90, elev=-60)
        ax.set_zlabel('depth (mm)', labelpad=15)
        args.data_draw.draw_raw3d_pose(ax, thedata, pose_raw)
        corners = cube.get_corners()
        iso_cube.draw_cube_wire(ax, corners)

        ax = mpplot.subplot(2, 4, 4, projection='3d')
        # grid = regu_grid()
        # grid.from_cube(cube, self.crop_size)
        # grid.draw_map(ax, frame_h5)
        args.data_draw.draw_raw3d_pose(ax, thedata, pose_raw)
        ax.view_init(azim=-90, elev=-75)
        ax.set_zlabel('depth (mm)', labelpad=15)

        pose_yank = self.yanker_hmap(
            resce3, vxhit_h5, self.hmap_size, self.caminfo)
        diff = np.abs(pose_raw - pose_yank)
        print(diff)
        print(np.min(diff, axis=0), np.max(diff, axis=0))
        voxel_crop = self.crop_size
        voxel_hmap = self.hmap_size
        grid = regu_grid()
        grid.from_cube(cube, voxel_crop)
        vxhit_crop = frame_h5

        ax = mpplot.subplot(2, 4, 5)
        pose3d = cube.transform_center_shrink(pose_raw)
        pose2d, _ = cube.project_ortho(pose3d, roll=0, sort=False)
        pose2d *= voxel_crop
        args.data_draw.draw_pose2d(
            ax, thedata,
            pose2d,
        )
        coord = grid.slice_ortho(vxhit_crop, roll=0)
        grid.draw_slice(ax, coord, 1.)
        ax.set_xlim([0, voxel_crop])
        ax.set_ylim([0, voxel_crop])
        ax.set_aspect('equal', adjustable='box')
        ax.invert_yaxis()

        ax = mpplot.subplot(2, 4, 6)
        pose3d = cube.transform_center_shrink(pose_yank)
        pose2d, _ = cube.project_ortho(pose3d, roll=1, sort=False)
        pose2d *= voxel_crop
        args.data_draw.draw_pose2d(
            ax, thedata,
            pose2d,
        )
        coord = grid.slice_ortho(vxhit_crop, roll=1)
        grid.draw_slice(ax, coord, 1.)
        ax.set_xlim([0, voxel_crop])
        ax.set_ylim([0, voxel_crop])
        ax.set_aspect('equal', adjustable='box')
        ax.invert_yaxis()

        from mpl_toolkits.axes_grid1 import make_axes_locatable
        from utils.image_ops import transparent_cmap
        ax = mpplot.subplot(2, 4, 7)
        vxhit_hmap = vxhit_crop[::2, ::2, ::2]
        coord = grid.slice_ortho(vxhit_hmap, roll=0)
        grid.draw_slice(ax, coord, 1.)
        vxhit_sum = np.zeros(voxel_hmap * voxel_hmap * voxel_hmap)
        # for ii in vxhit_h5.astype(int):
        #     vxhit_sum[ii] += 1
        vxhit_sum[vxhit_h5.astype(int)] = 1
        vxhit_sum = vxhit_sum.reshape((voxel_hmap, voxel_hmap, voxel_hmap))
        vxhit_axis = np.sum(vxhit_sum, axis=2)
        vxhit_axis = np.swapaxes(vxhit_axis, 0, 1)  # swap xy
        img_hit = ax.imshow(
            vxhit_axis, cmap=transparent_cmap(mpplot.cm.jet))
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        fig.colorbar(img_hit, cax=cax)
        ax.set_xlim([0, voxel_hmap])
        ax.set_ylim([0, voxel_hmap])
        ax.set_aspect('equal', adjustable='box')
        ax.invert_yaxis()

        ax = mpplot.subplot(2, 4, 8)
        vxhit_hmap = vxhit_crop[::2, ::2, ::2]
        coord = grid.slice_ortho(vxhit_hmap, roll=1)
        grid.draw_slice(ax, coord, 1.)
        vxhit_sum = np.zeros(voxel_hmap * voxel_hmap * voxel_hmap)
        # for ii in vxhit_h5.astype(int):
        #     vxhit_sum[ii] += 1
        vxhit_sum[vxhit_h5.astype(int)] = 1
        vxhit_sum = vxhit_sum.reshape((voxel_hmap, voxel_hmap, voxel_hmap))
        vxhit_axis = np.sum(vxhit_sum, axis=1)
        img_hit = ax.imshow(
            vxhit_axis, cmap=transparent_cmap(mpplot.cm.jet))
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        fig.colorbar(img_hit, cax=cax)
        ax.set_xlim([0, voxel_hmap])
        ax.set_ylim([0, voxel_hmap])
        ax.set_aspect('equal', adjustable='box')
        ax.invert_yaxis()

        # if self.args.show_draw:
        #     mlab.figure(size=(800, 800))
        #     points3_trans = cube.transform_to_center(points3_sam)
        #     mlab.points3d(
        #         points3_trans[:, 0], points3_trans[:, 1], points3_trans[:, 2],
        #         scale_factor=8,
        #         color=Color('lightsteelblue').rgb)
        #     mlab.outline()

        # if self.args.show_draw:
        #     mlab.figure(size=(800, 800))
        #     # mlab.contour3d(frame_h5)
        #     mlab.pipeline.volume(mlab.pipeline.scalar_field(frame_h5))
        #     mlab.pipeline.image_plane_widget(
        #         mlab.pipeline.scalar_field(frame_h5),
        #         plane_orientation='z_axes',
        #         slice_index=self.crop_size / 2)
        #     np.set_printoptions(precision=4)
        #     # print(frame_h5[12:20, 12:20, 16])
        #     mlab.outline()

        mpplot.savefig(os.path.join(
            args.predict_dir,
            'draw_{}_{}.png'.format(self.name_desc, img_id)))
        if self.args.show_draw:
            mpplot.show()
        print('[{}] drawing image #{:d} - done.'.format(
            self.name_desc, img_id))

    def get_model(
            self, input_tensor, is_training, bn_decay,
            hg_repeat=1, scope=None):
        """ input_tensor: BxHxWxDxC
            out_dim: BxHxWxDxJ, where J is number of joints
        """
        end_points = {}
        self.end_point_list = []
        final_endpoint = 'hourglass_{}'.format(hg_repeat - 1)
        num_joint = self.out_dim
        num_feature = 32
        num_vol = 32 * 32 * 32

        def add_and_check_final(name, net):
            end_points[name] = net
            return name == final_endpoint

        from tensorflow.contrib import slim
        from inresnet3d import inresnet3d
        # ~/anaconda2/lib/python2.7/site-packages/tensorflow/contrib/layers/
        with tf.variable_scope(
                scope, self.name_desc, [input_tensor]):
            weight_decay = 0.00004
            bn_epsilon = 0.001
            with \
                slim.arg_scope(
                    [slim.batch_norm],
                    is_training=is_training,
                    epsilon=bn_epsilon,
                    # # Make sure updates happen automatically
                    # updates_collections=None,
                    # Try zero_debias_moving_mean=True for improved stability.
                    # zero_debias_moving_mean=True,
                    decay=bn_decay), \
                slim.arg_scope(
                    [slim.dropout],
                    is_training=is_training), \
                slim.arg_scope(
                    [slim.fully_connected],
                    weights_regularizer=slim.l2_regularizer(weight_decay),
                    biases_regularizer=slim.l2_regularizer(weight_decay),
                    activation_fn=tf.nn.relu,
                    normalizer_fn=slim.batch_norm), \
                slim.arg_scope(
                    [slim.max_pool3d, slim.avg_pool3d],
                    stride=2, padding='SAME'), \
                slim.arg_scope(
                    [slim.conv3d_transpose],
                    stride=2, padding='SAME',
                    weights_regularizer=slim.l2_regularizer(weight_decay),
                    biases_regularizer=slim.l2_regularizer(weight_decay),
                    activation_fn=tf.nn.relu,
                    normalizer_fn=slim.batch_norm), \
                slim.arg_scope(
                    [slim.conv3d],
                    stride=1, padding='SAME',
                    weights_regularizer=slim.l2_regularizer(weight_decay),
                    biases_regularizer=slim.l2_regularizer(weight_decay),
                    activation_fn=tf.nn.relu,
                    normalizer_fn=slim.batch_norm):
                with tf.variable_scope('stage64'):
                    sc = 'stage64'
                    net = slim.conv3d(input_tensor, 16, 3)
                    net = inresnet3d.conv_maxpool(net, scope=sc)
                    self.end_point_list.append(sc)
                    if add_and_check_final(sc, net):
                        return net, end_points
                    sc = 'stage32_image'
                    net = inresnet3d.resnet_k(
                        net, scope='stage32_residual')
                    net = slim.conv3d(
                        net, num_feature, 1, scope='stage32_out')
                    self.end_point_list.append(sc)
                    if add_and_check_final(sc, net):
                        return net, end_points
                for hg in range(hg_repeat):  # 32x32x32
                    sc = 'hourglass_{}'.format(hg)
                    with tf.variable_scope(sc):
                        branch0 = inresnet3d.hourglass3d(
                            net, 2, scope=sc + '_hg')
                        branch0 = inresnet3d.resnet_k(
                            branch0, scope='_res')
                        branch_det = slim.conv3d(
                            branch0, num_joint, 1,
                            # normalizer_fn=None, activation_fn=tf.nn.softmax)
                            normalizer_fn=None, activation_fn=None)
                        branch_flat = tf.reshape(
                            branch_det,
                            [-1, num_vol, num_joint])
                        self.end_point_list.append(sc)
                        if add_and_check_final(sc, branch_flat):
                            return branch_flat, end_points
                        branch1 = slim.conv3d(
                            branch_det, num_feature, 1)
                        net = net + branch0 + branch1
        raise ValueError('final_endpoint (%s) not recognized', final_endpoint)

    def placeholder_inputs(self, batch_size=None):
        frames_tf = tf.placeholder(
            tf.float32, shape=(
                batch_size,
                self.crop_size, self.crop_size, self.crop_size,
                1))
        # hmap2_tf = tf.placeholder(
        #     tf.float32, shape=(
        #         batch_size,
        #         self.hmap_size, self.hmap_size,
        #         self.out_dim))
        # olmap_tf = tf.placeholder(
        #     tf.float32, shape=(
        #         batch_size,
        #         self.hmap_size, self.hmap_size,
        #         self.out_dim))
        # uomap_tf = tf.placeholder(
        #     tf.float32, shape=(
        #         batch_size,
        #         self.hmap_size, self.hmap_size,
        #         self.out_dim * 3))
        poses_tf = tf.placeholder(
            tf.int32, shape=(
                batch_size,
                self.out_dim))
        return frames_tf, poses_tf

    def get_loss(self, pred, echt, end_points):
        """ simple sum-of-squares loss
            pred: BxHxWxDxJ
            echt: BxJ
        """
        loss = 0
        # pred_shape = pred.shape
        for name, net in end_points.items():
            if not name.startswith('hourglass_'):
                continue
            echt_l = tf.unstack(echt, axis=-1)
            pred_l = tf.unstack(pred, axis=-1)
            vxhit_losses = [
                tf.nn.sparse_softmax_cross_entropy_with_logits(
                    labels=e, logits=p) for e, p in zip(echt_l, pred_l)]
            loss += tf.reduce_sum(tf.add_n(vxhit_losses))
        reg_losses = tf.add_n(tf.get_collection(
            tf.GraphKeys.REGULARIZATION_LOSSES))
        return loss + reg_losses
