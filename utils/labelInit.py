import torchdef gen_Hadamard(level):    meta=torch.tensor([[1,1],[1,-1]])    label=Hadamard(level, meta)    label=label[:level,:]    return labeldef Hadamard(level,meta):    if level/2>1:        meta=Hadamard(level/2,meta)        updata=torch.cat((meta,meta),dim=1)        downdata=torch.cat( (meta,-1*meta),dim=1)        result= torch.cat((updata,downdata),dim=0)        return result    else:        return meta