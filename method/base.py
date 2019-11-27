# -*- coding: utf-8 -*-
# @Time    : 2019/9/20 20:04

# @Author  : ChengBin

# @Desc : ==============================================

# ======================================================

# @Project : Label_embedding

# @FileName: base.py

# @Software: PyCharm


import torch
import torch.nn.functional as F
import numpy as np

def CrossEntropyLoss(logit, prob):
    """ Cross-entropy function"""
    soft_logit = F.log_softmax(logit, dim=1)
    prob.type(torch.cuda.FloatTensor)
    Entrophy = prob.mul(soft_logit)
    loss = -1 * torch.sum(Entrophy, 1)
    loss = torch.mean(loss)
    return loss

def KL_Divergence(prob1, prob2):
    KLD = prob1.mul(torch.log(prob1)) - prob1.mul(torch.log(prob2))
    loss = torch.sum(KLD, 1)
    loss = torch.mean(loss)
    return loss

def Mseloss(outputs, targets):
    """ MSE function"""
    return ((outputs - targets) ** 2).mean()


class LabelProcessor(object):
    def __init__(self):
        pass

    def reset(self):
        pass

    def append(self):
        pass

    def set(self):
        pass

class Criterion:
    def __init__(self):
        #super(Criterion, self).__init__()
        self.preds = []
        self.targets = []
        self.idx = []
        self.labelprocessor = LabelProcessor()
        self.loss = []

    def process(self, epoch=None, args=None):
        pass

    def prepare(self, inputs, targets):
        inputs, targets = torch.autograd.Variable(inputs), torch.autograd.Variable(targets)
        return inputs.cuda(), targets.cuda(async=True)

    def __call__(self, preds, targets, idx, epoch=None):
        pass

class cross_entropy_criterion(Criterion):
    def __init__(self):
        pass
    #    super(cross_entropy_criterion,self).__init__()
    #def prepare(self, inputs, targets):
    #    pass

    def __call__(self, preds, targets, idx, epoch):
        return torch.nn.functional.cross_entropy(preds, targets)

class soft_label_criterion(Criterion):
    def __init__(self, init_label):
        super(soft_label_criterion, self).__init__()
        use_cuda = torch.cuda.is_available()
        self.soft_label = init_label.detach()
        if use_cuda:
            self.soft_label = self.soft_label.cuda()

    def __call__(self, preds, targets, idx, epoch):
        loss = CrossEntropyLoss(preds, self.soft_label[idx, :])
        return loss

    def process(self, epoch=None, args=None, **kwargs):
        if 'soft_label' in kwargs:
            self.soft_label = kwargs['soft_label']


class CategoryLabelProcessor():
    def __init__(self, Num, alpha=0.01, p=0.5, is_select=True):
        self.N = Num
        self.number = torch.zeros(Num, 1).cuda()
        self.result = torch.zeros(Num, Num).cuda()
        self.emsemble_label = torch.eye(Num).cuda()
        self.alpha = alpha
        self.p = p
        self.is_select = is_select

    def reset(self, epoch, args):
        self.number = torch.zeros(self.N, 1).cuda()
        self.result = torch.zeros(self.N, self.N).cuda()

    def append(self, output, target):
        batch = target.size(0)
        feature_num = self.N
        mask = torch.zeros(batch, self.N).cuda()
        mask = mask.scatter_(1, target.view(batch, 1).cuda(), 1)  # N*k 每一行是一个one-hot向量

        if self.is_select == True:
            _, predicted = torch.max(output.data, 1)
            index = (predicted == target)
            select = index.view(batch, 1).type(torch.cuda.FloatTensor)
            mask = mask.type(torch.cuda.FloatTensor) * select

        mask = mask.view(batch, self.N, 1)  # N*k*1 目的是扩成 N*k*s
        soft_logit = torch.nn.functional.softmax(output, dim=1)
        output_ex = soft_logit.view(batch, 1, feature_num)  # N*1*s 目的是扩成 N*k*s
        sum = torch.sum(output_ex * mask, dim=0)

        self.result += sum
        self.number += mask.sum(dim=0)

    def update(self):
        index = (self.number != 0)
        index2 = index.view(1, -1).squeeze()
        newlabel = self.p * torch.eye(self.N)[index2, :].cuda() + (1 - self.p) * self.result[index2, :] / self.number[
            index].view(-1, 1)
        self.emsemble_label[index2, :] = (1 - self.alpha) * self.emsemble_label[index2, :] + self.alpha * newlabel
        return self.emsemble_label

class Dirichelet_CategoryLabelProcessor():
    def __init__(self, Num, init_factor, prior_type):
        self.N = Num
        self.init_D_parm = init_factor * torch.eye(Num).cuda()
        self.D_parm = self.init_D_parm
        self.emsemble_label = torch.eye(Num).cuda()
        self.total = torch.zeros(self.N, 1).cuda()
        self.result = torch.zeros(self.N, self.N).cuda()
        self.prior_type = prior_type

    def reset(self, epoch, args):
        self.result = torch.zeros(self.N, self.N).cuda()

    def append(self, output, target):
        batch = target.size(0)
        classnum = self.N
        mask = torch.zeros(batch, self.N).cuda()
        target_mask = mask.scatter(1, target.view(batch, 1).cuda(), 1)  # N*k 每一行是一个one-hot向量,全部的数目

        _, predicted = torch.max(output.data, 1)
        predicted_mask = mask.scatter(1, predicted.view(batch, 1).cuda(), 1)

        statistics = torch.bmm(target_mask.view(batch, classnum, 1), predicted_mask.view(batch, 1, classnum))
        self.result += torch.sum(statistics, dim=0)

    def update(self):
        if self.prior_type == 'one_hot':
            self.D_parm = self.init_D_parm + self.result
        elif self.prior_type == 'history':
            self.D_parm = self.D_parm + self.result
        else:
            self.D_parm = self.init_D_parm + self.D_parm + self.result

        total = self.D_parm.sum(dim=1)
        self.emsemble_label = self.D_parm / total.view(-1, 1)

        return self.emsemble_label

class CategoryLabelProcessCriterion(Criterion):
    def __init__(self, Num, alpha=0.01, p=0.5, is_select=False, model_type='simple', loss_type='CE', namda=1,
                 process_type='nomal', init_factor=10, prior_type='one_hot'):
        super(CategoryLabelProcessCriterion, self).__init__()
        self.model_type = model_type
        self.loss_type = loss_type
        if process_type == 'dirichlet':
            self.processor = Dirichelet_CategoryLabelProcessor(Num, init_factor, prior_type)
        else:
            self.processor = CategoryLabelProcessor(Num, alpha, p, is_select)
        self.CE_criterion = torch.nn.CrossEntropyLoss()
        self.KL_criterion = torch.nn.KLDivLoss()
        self.namda = namda
        self.process_type = process_type

    def __call__(self, preds, targets, idx, epoch):
        emsemble_label = self.processor.emsemble_label
        if self.model_type == 'simple':
            if self.loss_type == 'CE':
                loss = CrossEntropyLoss(preds, emsemble_label[targets, :])
            if self.loss_type == 'KLD':
                loss = self.KL_criterion(F.log_softmax(preds, dim=1), emsemble_label[targets, :])
        elif self.model_type == 'combination':
            if self.loss_type == 'CE':
                loss = self.CE_criterion(preds, targets) + self.namda * CrossEntropyLoss(preds,
                                                                                         emsemble_label[targets, :])
            if self.loss_type == 'KLD':
                loss = self.CE_criterion(preds, targets) + self.namda * self.KL_criterion(F.log_softmax(preds, dim=1),
                                                                                          emsemble_label[targets, :])

        with torch.no_grad():
            self.processor.append(preds, targets)

        return loss

    def process(self, epoch=None, args=None):
        if epoch % args.clTE_update_interval == 0 and epoch >= args.clTE_start_epoch:
            print('\n update emsemble label')
            self.processor.update()
            if self.process_type == 'dirichlet':
                print("D_parm is : \n {} \n label is : \n {} \n ".format(self.processor.D_parm,
                                                                         self.processor.emsemble_label))
            else:
                print(self.processor.emsemble_label)

            self.processor.reset(epoch, args)

class Dirichelet_SampleLabelProcessor():
    def __init__(self, Num, class_num, init_factor, prior_type):
        self.N = Num
        self.class_num = class_num
        self.init_factor = init_factor
        self.init_D_parm = torch.zeros(self.N, class_num).cuda()
        self.D_parm = self.init_D_parm

        self.emsemble_label = torch.zeros(self.N, class_num).cuda()
        self.result = torch.zeros(self.N, class_num).cuda()
        self.prior_type = prior_type
        self.targets = -1 * torch.ones(self.N).type(torch.cuda.LongTensor)

    def class2one_hot(self, outputs, labels):
        class_mask = outputs.new_zeros(outputs.size())
        label_ids = labels.view(-1, 1)
        class_mask.scatter_(1, label_ids, 1.)
        return class_mask

    def reset(self, epoch, args=None):
        self.result = torch.zeros(self.N, self.class_num).cuda()

    def append(self, output, target, idx, epoch):
        if epoch == 0:
            self.targets[idx] = target
            self.init_D_parm[idx, :] = self.init_factor * self.class2one_hot(output, target)
            self.D_parm[idx, :] = self.init_D_parm[idx, :]
            self.emsemble_label[idx, :] = self.class2one_hot(output, target)

        batch = target.size(0)
        num_classes = output.size(1)

        mask = torch.zeros(batch, num_classes).cuda()
        _, predicted = torch.max(output.data, 1)
        predicted_mask = mask.scatter(1, predicted.view(batch, 1).cuda(), 1)
        self.result[idx, :] += predicted_mask

    def update(self):
        if self.prior_type == 'one_hot':
            self.D_parm = self.init_D_parm + self.result
        elif self.prior_type == 'history':
            self.D_parm = self.D_parm + self.result
        else:
            self.D_parm = self.init_D_parm + self.D_parm + self.result

        total = self.D_parm.sum(dim=1)
        self.emsemble_label = self.D_parm / total.view(-1, 1)

        return self.emsemble_label

class SampleLabelProcessCriterion(Criterion):
    def __init__(self, args):
        super(SampleLabelProcessCriterion, self).__init__()

        self.process_type = args.process_type

        if args.process_type == 'dirichlet':
            self.processor = Dirichelet_SampleLabelProcessor(args.num_samples, args.num_classes,
                                                             args.init_factor, args.prior_type)

    def __call__(self, preds, targets, idx, epoch):
        with torch.no_grad():
            self.processor.append(preds, targets, idx, epoch)

        loss = CrossEntropyLoss(preds, self.processor.emsemble_label[idx, :])

        return loss

    def process(self, epoch=None, args=None):
        if epoch % args.slTE_update_interval == 0 and epoch >= args.slTE_start_epoch:
            print('\n update emsemble label')
            self.processor.update()
            if self.process_type == 'dirichlet':
                print("D_parm is : \n {} \n label is : \n {} \n ".format(self.processor.D_parm.cpu().numpy(),
                                                                         self.processor.emsemble_label.cpu().numpy()))
            else:
                print(self.processor.emsemble_label.cpu().numpy())

            self.processor.reset(epoch, args)

class beyesianSnapshotCriterion(Criterion):
    def __init__(self, args):
        super(beyesianSnapshotCriterion, self).__init__()
        self.process_type = args.process_type
        if args.process_type == 'dirichlet':
            self.processor = Dirichelet_SampleLabelProcessor(args.num_samples, args.num_classes,
                                                             args.init_factor, args.prior_type)

        num_samples = args.num_samples
        num_classes = args.num_classes
        T = args.SD_T
        interal = args.SD_interval

        self.interal = interal
        self.record_label = torch.zeros(size=(T, num_samples, num_classes)).type(torch.cuda.FloatTensor)
        self.milestones = torch.zeros(size=(T - 1, 1))
        for i in range(T - 1):
            self.milestones[i] = (i + 1) * interal
        self.CE_criterion = torch.nn.CrossEntropyLoss()
        self.KL_criterion = torch.nn.KLDivLoss()
        self.lds = 1 + 1 / 3
        self.period = 0

    def __call__(self, preds, targets, idx, epoch):
        with torch.no_grad():
            self.processor.append(preds, targets, idx, epoch)
            self.processor.update()

        if epoch in self.milestones:
            self.period = epoch // self.interal
            T = self.period
            with torch.no_grad():
                self.record_label[T, idx, :] = self.processor.emsemble_label[idx, :]
                self.processor.reset(epoch)

        if epoch <= self.interal:
            return self.CE_criterion(preds, targets)
        else:
            T = self.period
            loss = self.CE_criterion(preds, targets) + \
                   self.lds * self.KL_criterion(F.log_softmax(preds, dim=1), self.record_label[T, idx, :])
            return loss

    def process(self, epoch=None, args=None):
        print('\n update emsemble label')

        if self.process_type == 'dirichlet':
            print("D_parm is : \n {} \n label is : \n {} \n ".format(self.processor.D_parm.cpu().numpy(),
                                                                     self.processor.emsemble_label.cpu().numpy()))
        else:
            print(self.processor.emsemble_label.cpu().numpy())

class AlternateCategoryLabelProcessCriterion(Criterion):
    def __init__(self, Num, alpha=0.01, p=0.5, is_select=False, model_type='simple', loss_type='CE', namda=1,
                 process_type='nomal',
                 init_factor=10, Alternate_interval=30, Alternate_rate=0.5, is_no_one_hot=False):
        super(AlternateCategoryLabelProcessCriterion, self).__init__()
        self.model_type = model_type
        self.loss_type = loss_type
        if process_type == 'dirichlet':
            self.processor = Dirichelet_CategoryLabelProcessor(Num, init_factor, is_no_one_hot)
        else:
            self.processor = CategoryLabelProcessor(Num, alpha, p, is_select)
        self.CE_criterion = torch.nn.CrossEntropyLoss()
        self.KL_criterion = torch.nn.KLDivLoss()
        self.namda = namda
        self.process_type = process_type
        self.Alternate_interval = Alternate_interval
        self.Alternate_rate = Alternate_rate
        self.one_hot_label = torch.eye(Num).cuda()

    def __call__(self, preds, targets, idx, epoch):
        emsemble_label = self.processor.emsemble_label
        if (epoch % self.Alternate_interval) > (self.Alternate_interval * self.Alternate_rate):
            target_label = emsemble_label
        else:
            target_label = self.one_hot_label
            with torch.no_grad():
                self.processor.append(preds, targets)

        if self.model_type == 'simple':
            if self.loss_type == 'CE':
                loss = CrossEntropyLoss(preds, target_label[targets, :])
            if self.loss_type == 'KLD':
                loss = self.KL_criterion(F.log_softmax(preds, dim=1), target_label[targets, :])
        elif self.model_type == 'combination':
            if self.loss_type == 'CE':
                loss = self.CE_criterion(preds, targets) + self.namda * CrossEntropyLoss(preds,
                                                                                         target_label[targets, :])
            if self.loss_type == 'KLD':
                loss = self.CE_criterion(preds, targets) + self.namda * self.KL_criterion(F.log_softmax(preds, dim=1),
                                                                                          target_label[targets, :])

        return loss

    def process(self, epoch=None, args=None):
        if epoch % args.clTE_update_interval == 0 and epoch >= args.clTE_start_epoch:
            if (epoch % self.Alternate_interval) > (self.Alternate_interval * self.Alternate_rate):
                print('\n use emsemble label')
            else:
                print('\n use one_hot label and update emsemble label')
                print('\n ')
                self.processor.update()

            if self.process_type == 'dirichlet':
                print("D_parm is : \n {} \n label is : \n {} \n ".format(self.processor.D_parm,
                                                                         self.processor.emsemble_label))
            else:
                print(self.processor.emsemble_label)

            self.processor.reset(epoch, args)


class TCRLabelProcessor():
    def __init__(self, num_samples, num_classes, delay_epoch=1, is_average=False):
        super(TCRLabelProcessor, self).__init__()
        self.delay_epoch = delay_epoch
        self.record_label = torch.zeros(size=(num_samples, num_classes)).type(torch.cuda.FloatTensor)

    def append(self, outputs, sample_idx):
        ans = F.softmax(outputs, dim=1)
        self.record_label[sample_idx, :] = ans

    def get_label(self, sample_idx):
        return self.record_label[sample_idx, :]

class TCRCriterion(Criterion):
    def __init__(self, num_samples, num_classes, start_epoch, beta, start_squeeze, squeeze_ratio=1.1, stop_epoch=300):
        super(TCRCriterion, self).__init__()
        self.beta = beta
        self.start_epoch = start_epoch
        self.stop_epoch = stop_epoch
        self.start_squeeze = start_squeeze
        self.squeeze_ratio = squeeze_ratio
        self.lprocessor = TCRLabelProcessor(num_samples, num_classes)
        self.loss = CrossEntropyLoss

    def __call__(self, preds, targets, idx, epoch):

        weight_targets = self.get_weight_targets(preds, targets, idx, epoch)

        with torch.no_grad():
            self.lprocessor.append(preds, idx)
        loss = CrossEntropyLoss(preds, weight_targets)

        return loss

    def get_weight_targets(self, outputs, targets, idx, epoch):
        class_mask = outputs.new_zeros(size=outputs.size()).cuda()
        ids = targets.view(-1, 1)
        class_mask.scatter_(1, ids, 1.)

        beta = self.beta
        if epoch >= self.start_epoch:

            pred = self.lprocessor.get_label(idx)
            if epoch >= self.start_squeeze:
                unnormed_pred = pred.pow(self.squeeze_ratio)
                pred = unnormed_pred / unnormed_pred.sum(dim=1, keepdim=True)

            targets = beta * class_mask + (1. - beta) * pred
        else:
            targets = class_mask
        return targets

    def process(self, epoch=None, args=None):
        print(self.lprocessor.get_label(0))


class SnapshotCriterion(Criterion):
    def __init__(self, num_samples, num_classes, T, interal):
        super(SnapshotCriterion, self).__init__()
        self.interal = interal
        self.record_label = torch.zeros(size=(T, num_samples, num_classes)).type(torch.cuda.FloatTensor)
        self.milestones = torch.zeros(size=(T - 1, 1))
        for i in range(T - 1):
            self.milestones[i] = (i + 1) * interal
        self.CE_criterion = torch.nn.CrossEntropyLoss()
        self.KL_criterion = torch.nn.KLDivLoss()
        self.lds = 1 + 1 / 3
        self.period = 0

    def __call__(self, preds, targets, idx, epoch):
        if epoch in self.milestones:
            self.period = epoch // self.interal
            T = self.period
            with torch.no_grad():
                self.record_label[T, idx, :] = F.softmax(preds, dim=1)

        if epoch <= self.interal:
            return self.CE_criterion(preds, targets)
        else:
            T = self.period
            loss = self.CE_criterion(preds, targets) + \
                   self.lds * self.KL_criterion(F.log_softmax(preds, dim=1), self.record_label[T, idx, :])
            return loss


class Penalizing_Confident_criterion(Criterion):
    def __init__(self):
        super(Penalizing_Confident_criterion, self).__init__()

    def __call__(self, preds, targets, idx, epoch):
        logit = F.softmax(preds, dim=1)
        Entropy = -1 * torch.mean(torch.sum(logit.mul(logit), 1))
        return torch.nn.functional.cross_entropy(preds, targets) + 0.1 * Entropy


def gen_Hadamard(level):
    meta = torch.tensor([[1, 1], [1, -1]])
    label = Hadamard(level, meta)
    label = label[:level, :]
    return label


def Hadamard(level, meta):
    if level / 2 > 1:
        meta = Hadamard(level / 2, meta)
        updata = torch.cat((meta, meta), dim=1)
        downdata = torch.cat((meta, -1 * meta), dim=1)
        result = torch.cat((updata, downdata), dim=0)
        return result
    else:
        return meta


class metric_label_model(torch.nn.Module):
    def __init__(self, model, num_classes, metric_label_type='one_hot',
                 feature_num=None):
        super(metric_label_model, self).__init__()

        if metric_label_type == 'one_hot':
            feature_num = num_classes
            self.maplabel = torch.nn.Parameter(torch.Tensor(num_classes, feature_num))
            self.maplabel.data = torch.eye(num_classes).cuda()
        elif metric_label_type == 'hadamard':
            hadamard_mat = gen_Hadamard(num_classes)
            feature_num = hadamard_mat.size(1)
            self.maplabel = torch.nn.Parameter(torch.Tensor(num_classes, feature_num))
            self.maplabel.data = hadamard_mat.type(torch.cuda.FloatTensor)
        print("feature num : {}".format(feature_num))

        # self.maplabel= torch.nn.Parameter(torch.Tensor(maplabel.size()))
        feature_num = self.maplabel.size(1)
        fc = list(model.children())[-1]
        in_features = fc.in_features
        model.fc = torch.nn.Linear(in_features, feature_num)
        self.model = model

    def Euclid(self, W, x):

        batch_size = x.size(0)
        num_classes = W.size(0)
        dists = torch.zeros(num_classes, batch_size).cuda()
        dists += torch.sum(x ** 2, dim=1).reshape(1, batch_size)
        dists += torch.sum(W ** 2, dim=1).reshape(num_classes, 1)
        dists -= 2 * W.mm(x.t())
        dists = torch.clamp(dists, min=0)
        dists = torch.sqrt(dists)
        dists = -1 * dists
        dists = dists.t()

        # num_classes = W.size(0)
        # dists = x[:,:num_classes]
        return dists

    ## Cosine 有尺度问题
    def Cosine(self, W, x):
        W_norm = W.norm(p=2, dim=1)
        x_norm = x.norm(p=2, dim=1)
        cos_theta = x.mm(W.t()) / (W_norm * x_norm.view(-1, 1))
        cos_theta = cos_theta.clamp(-1, 1)
        return cos_theta

    def forward(self, x):
        x = self.model(x)
        out = self.Euclid(self.maplabel, x)
        return out

class metric_label_criterion(Criterion):
    def __init__(self, model):
        super(metric_label_criterion, self).__init__()
        self.model = model

    def forward(self, preds, targets, idx, epoch):
        loss = torch.nn.functional.cross_entropy(preds, targets)
        return loss

    def process(self, epoch=None, args=None):
        print(self.model.maplabel)

class MetricLabelProcessor():
    def __init__(self, Num, feature_num, init_label, alpha=0.01, p=0.5, is_select=True):
        self.N = Num
        self.feature_num = feature_num
        self.init_label = init_label
        self.number = torch.zeros(Num, 1).cuda()
        self.result = torch.zeros_like(init_label).cuda()
        self.emsemble_label = init_label.cuda()
        self.alpha = alpha
        self.p = p
        self.is_select = is_select

    def reset(self, epoch, args):
        self.number = torch.zeros(self.N, 1).cuda()
        self.result = torch.zeros_like(self.init_label).cuda()

    def append(self, output, target):
        batch = target.size(0)
        feature_num = self.feature_num
        mask = torch.zeros(batch, self.N).cuda()
        mask = mask.scatter_(1, target.view(batch, 1).cuda(), 1)  # N*k 每一行是一个one-hot向量

        if self.is_select == True:
            _, predicted = torch.max(output.data, 1)
            index = (predicted == target)
            select = index.view(batch, 1).type(torch.cuda.FloatTensor)
            mask = mask.type(torch.cuda.FloatTensor) * select

        mask = mask.view(batch, self.N, 1)  # N*k*1 目的是扩成 N*k*s
        # soft_logit = torch.nn.functional.softmax(output, dim=1)
        # print(output,output.shape)
        output_ex = output.view(batch, 1, feature_num)  # N*1*s 目的是扩成 N*k*s
        sum = torch.sum(output_ex * mask, dim=0)

        self.result += sum
        self.number += mask.sum(dim=0)

    def update(self):
        index = (self.number != 0)
        index2 = index.view(1, -1).squeeze()
        newlabel = self.p * self.init_label[index2, :].cuda() + (1 - self.p) * self.result[index2, :] / self.number[
            index].view(-1, 1)
        self.emsemble_label[index2, :] = (1 - self.alpha) * self.emsemble_label[index2, :] + self.alpha * newlabel
        return self.emsemble_label

class metric_label_ensemble_criterion(Criterion):
    def __init__(self, model, num_classes, metric_label_type='one_hot',
                 feature_num=None, alpha=0.01, p=0.5, is_select=True):
        super(metric_label_ensemble_criterion, self).__init__()
        if metric_label_type == 'one_hot':
            feature_num = num_classes
        elif metric_label_type == 'hadamard':
            hadamard_mat = gen_Hadamard(num_classes)
            feature_num = hadamard_mat.size(1)

        print("feature num : {}".format(feature_num))

        self.maplabel = torch.Tensor(num_classes, feature_num)
        if metric_label_type == 'one_hot':
            self.maplabel.data = torch.eye(num_classes).cuda()
        elif metric_label_type == 'hadamard':
            self.maplabel.data = hadamard_mat.type(torch.cuda.FloatTensor)
        print('init label:')
        print(self.maplabel.data)

        self.processor = MetricLabelProcessor(num_classes, feature_num, self.maplabel, alpha, p, is_select)
        self.CE_Loss = torch.nn.CrossEntropyLoss()

        fc = list(model.children())[-1]
        in_features = fc.in_features
        model.fc = torch.nn.Linear(in_features, feature_num)
        # model = torch.nn.Sequential(*list(model.children())[:-1])
        # model.add_module('new_fc', torch.nn.Linear(in_features, feature_num))

        self.model = model.cuda()

    def __call__(self, preds, targets, idx, epoch):
        real_preds = self.Euclid(self.processor.emsemble_label, preds)
        loss = self.CE_Loss(real_preds, targets)
        with torch.no_grad():
            self.processor.append(preds, targets)
        return loss

    def process(self, epoch=None, args=None):
        print('\n update emsemble label')
        self.processor.update()
        print(self.processor.emsemble_label)
        self.processor.reset(epoch, args)

    def Euclid(self, W, x):
        batch_size = x.size(0)
        num_classes = W.size(0)
        dists = torch.zeros(num_classes, batch_size).cuda()
        dists += torch.sum(x ** 2, dim=1).reshape(1, batch_size)
        dists += torch.sum(W ** 2, dim=1).reshape(num_classes, 1)
        dists -= 2 * W.mm(x.t())
        dists = torch.clamp(dists, min=0)
        dists = torch.sqrt(dists)
        dists = -1 * dists
        dists = dists.t()
        return dists


class label_select_criterion(Criterion):
    def __init__(self, num_samples, num_classses):
        self.b = torch.zeros(num_samples).type(torch.cuda.FloatTensor)
        self.miu = torch.zeros(size=(num_samples, num_classses)).type(torch.cuda.FloatTensor)
        self.num_classses = num_classses
        self.is_select = True

    def __call__(self, preds, targets, idx, epoch):
        if epoch == 0:
            self.miu[idx, :] = preds
            return torch.nn.functional.cross_entropy(preds, targets)
        else:
            # print(torch.mean((self.miu[idx,:]-preds)**2,dim=1).shape)
            with torch.no_grad():
                self.b[idx] = torch.mean((self.miu[idx, :] - preds) ** 2, dim=1)
                weight = self.b[idx].view(-1, 1)
                self.miu[idx, :] = preds
                if self.is_select == True:
                    _, predicted = torch.max(preds.data, 1)
                    index = 1 - (predicted == targets)
                    select = 5 * index.view(-1, 1).type(torch.cuda.FloatTensor) + 1
                    weight = select * weight
                    self.b[idx] = weight.view(-1)

            return torch.nn.functional.cross_entropy(weight * preds, targets)

    def process(self, epoch=None, args=None):
        print(self.b[1].data)








































