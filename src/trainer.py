import time
from pathlib import Path

import numpy as np

import torch
from torch import nn
from torch.autograd import Variable
import torch.optim as optim

from logger import Logger

class Trainer(object):
    def __init__(self, dataloader, configs):

        self.batchsize = configs["batchsize"]
        self.max_iteration = configs["iterations"]
        self.video_length = configs["video_length"]

        self.dataloader = dataloader
        self.data_enumerater = enumerate(dataloader)
        
        self.log_dir = Path(configs["log_dir"]) / configs["experiment_name"]
        self.tensorboard_dir = Path(configs["tensorboard_dir"]) / configs["experiment_name"]
        self.logger = Logger(dataloader, configs)

        self.evaluation_interval  = configs["evaluation_interval"]
        self.log_samples_interval = configs["log_samples_interval"]

        self.gan_criterion = nn.BCEWithLogitsLoss(reduction='sum')
        self.use_cuda = torch.cuda.is_available()
        self.device = self.use_cuda and torch.device('cuda') or torch.device('cpu')
        self.configs = configs

    def sample_real_batch(self):
        batch_idx, batch = next(self.data_enumerater)
        if self.use_cuda:
            batch = batch.cuda()

        if batch_idx == len(self.dataloader) - 1:
            self.data_enumerator = enumerate(self.dataloader)

        return batch.float()

    def create_optimizer(self, model, lr, decay):
        return optim.Adam(
                model.parameters(),
                lr=lr,
                betas=(0.5, 0.999),
                weight_decay=decay,
                )

    def compute_dis_loss(self, y_real, y_fake):
        ones = torch.ones_like(y_real, device=self.device)
        zeros = torch.zeros_like(y_fake, device=self.device)

        loss  = self.gan_criterion(y_real, ones)  / y_real.numel()
        loss += self.gan_criterion(y_fake, zeros) / y_fake.numel()

        return loss

    def compute_gen_loss(self, y_fake_i, y_fake_v):
        ones_i = torch.ones_like(y_fake_i, device=self.device)
        ones_v = torch.ones_like(y_fake_v, device=self.device)

        loss  = self.gan_criterion(y_fake_i, ones_i) / y_fake_i.numel()
        loss += self.gan_criterion(y_fake_v, ones_v) / y_fake_v.numel()

        return loss

    def train(self, gen, idis, vdis):
        if self.use_cuda:
            gen.cuda()
            idis.cuda()
            vdis.cuda()
        
        # create optimizers
        configs = self.configs
        opt_gen  = self.create_optimizer(gen,  **configs["gen"]["optimizer"])
        opt_idis = self.create_optimizer(idis, **configs["idis"]["optimizer"])
        opt_vdis = self.create_optimizer(vdis, **configs["vdis"]["optimizer"])

        # training loop
        logger = self.logger
        while True:
            #--------------------
            # phase generator
            #--------------------

            gen.train();  opt_gen.zero_grad()

            # fake batch
            x_fake = gen.sample_videos(self.batchsize).float()

            t_rand = np.random.randint(self.video_length)
            y_fake_i = idis(x_fake[:,:,t_rand])
            y_fake_v = vdis(x_fake)

            # compute loss
            loss_gen = self.compute_gen_loss(y_fake_i, y_fake_v)

            # update weights
            loss_gen.backward(); opt_gen.step()


            #--------------------
            # phase discriminator
            #--------------------
            
            idis.train(); opt_idis.zero_grad()
            vdis.train(); opt_vdis.zero_grad()

            # real batch
            x_real = Variable(self.sample_real_batch())

            y_real_i = idis(x_real[:,:,t_rand])
            y_real_v = vdis(x_real)

            y_fake_i = idis(x_fake[:,:,t_rand].detach())
            y_fake_v = vdis(x_fake.detach())
            
            # compute loss
            loss_idis = self.compute_dis_loss(y_real_i, y_fake_i)
            loss_vdis = self.compute_dis_loss(y_real_v, y_fake_v)

            # update weights
            loss_idis.backward(); opt_idis.step()
            loss_vdis.backward(); opt_vdis.step()

            #--------------------
            # logging
            #--------------------
            
            logger.update("loss_gen",  loss_gen.cpu().item())
            logger.update("loss_idis", loss_idis.cpu().item())
            logger.update("loss_vdis", loss_vdis.cpu().item())
            logger.next_iter()

            # # # generate samples
            # # if iteration % log_samples_interval == 0:
            # #     generator.eval()
            # #
            # #     images, _ = sample_fake_image_batch(self.image_batch_size)
            # #     logger.image_summary("Images", images_to_numpy(images), iteration)
            # #
            # #     videos, _ = sample_fake_video_batch(self.video_batch_size)
            # #     logger.video_summary("Videos", videos_to_numpy(videos), iteration)
            # #
            # # # evaluate generator samples
            # # if iteration % self.evaluation_interval == 0:
            # #    pass
            #
            # if iteration >= self.max_iteration:
            #     torch.save(generator, str(self.log_folder/'gen_{:05d}.pytorch'.format(iteration)))
            #     break