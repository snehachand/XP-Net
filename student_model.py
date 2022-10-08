from collections import OrderedDict
import torch
import torch.nn as nn
import torch
import torch.nn as nn
import torchvision.transforms.functional as TF
# import hiddenlayer as hl
import matplotlib.pyplot as plt
from torchsummary import summary
torch.cuda.empty_cache()



def conv(in_planes, out_planes, kernel_size=3, stride=1, padding=1, dilation=1, groups=1):
    """standard convolution with padding"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=kernel_size, stride=stride,
                     padding=padding, dilation=dilation, groups=groups, bias=False)

def conv1x1(in_planes, out_planes, stride=1):
    """1x1 convolution"""
    return nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride, bias=False)



class SEWeightModule(nn.Module):

    def __init__(self, channels, reduction=8):
        super(SEWeightModule, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Conv2d(channels, channels//reduction, kernel_size=1, padding=0)
        nn.init.kaiming_uniform_(self.fc1.weight)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Conv2d(channels//reduction, channels, kernel_size=1, padding=0)
        nn.init.kaiming_uniform_(self.fc2.weight)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out = self.avg_pool(x)
        out = self.fc1(out)
        out = self.relu(out)
        out = self.fc2(out)
        weight = self.sigmoid(out)


        return weight
    
    
    
class PSAModule(nn.Module):

    def __init__(self, inplans, planes, conv_kernels=[3, 5, 7, 9], stride=1, conv_groups=[1,2, 4, 8]):
        super(PSAModule, self).__init__()
        self.conv_1 = conv(inplans, planes//4, kernel_size=conv_kernels[0], padding=conv_kernels[0]//2,
                            stride=stride, groups=conv_groups[0])
        nn.init.kaiming_uniform_(self.conv_1.weight)
        self.conv_2 = conv(inplans, planes//4, kernel_size=conv_kernels[1], padding=conv_kernels[1]//2,
                            stride=stride, groups=conv_groups[1])
        nn.init.kaiming_uniform_(self.conv_2.weight)
        self.conv_3 = conv(inplans, planes//4, kernel_size=conv_kernels[2], padding=conv_kernels[2]//2,
                            stride=stride, groups=conv_groups[2])
        nn.init.kaiming_uniform_(self.conv_3.weight)
        self.conv_4 = conv(inplans, planes//4, kernel_size=conv_kernels[3], padding=conv_kernels[3]//2,
                            stride=stride, groups=conv_groups[3])
        nn.init.kaiming_uniform_(self.conv_4.weight)
            
        self.se = SEWeightModule(planes // 4)
        self.split_channel = planes // 4
        self.softmax = nn.Softmax(dim=1)
    def forward(self, x):
        batch_size = x.shape[0]
        planes= x.shape[1]
#         print(planes)
        x1 = self.conv_1(x)
        x2 = self.conv_2(x)
        x3 = self.conv_3(x)
        x4 = self.conv_4(x)

        feats = torch.cat((x4, x3, x2, x1), dim=1)
        feats = feats.view(batch_size, 4, self.split_channel, feats.shape[2], feats.shape[3])

        x1_se = self.se(x1)
        x2_se = self.se(x2)
        x3_se = self.se(x3)
        x4_se = self.se(x4)

        x_se = torch.cat((x4_se,x3_se,x2_se,x1_se), dim=1)
        attention_vectors = x_se.view(batch_size, 4, self.split_channel, 1, 1)
        attention_vectors = self.softmax(attention_vectors)
        feats_weight = feats * attention_vectors
#         print(f'feats_weight.shape {feats_weight.shape}')
# 
        out = feats_weight.view(batch_size,planes,feats.shape[3], feats.shape[4])
           
#         print(f'out.shape {out.shape}')

        return out
    
class DoubleConv_for_EPAB(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(DoubleConv_for_EPAB, self).__init__()
        self.conv1 = nn.Conv2d(in_channels, out_channels, 3, 1, 1, bias=False)
        nn.init.kaiming_uniform_(self.conv1.weight,mode='fan_in')
        self.bn1=nn.BatchNorm2d(out_channels)
        self.lrelu_1=nn.LeakyReLU(inplace=True)
        self.Psa=PSAModule(out_channels,out_channels)
        self.conv2 = nn.Conv2d(out_channels, out_channels, 3, 1, 1, bias=False)
        nn.init.kaiming_uniform_(self.conv2.weight,mode='fan_in')
        self.bn2=nn.BatchNorm2d(out_channels)
        self.lrelu_2=nn.LeakyReLU(inplace=True)
        

    def forward(self, x):
        x=self.conv1(x)
        x=self.bn1(x)
        x=self.lrelu_1(x)
        x=self.Psa(x)
        x=self.conv2(x)
        x=self.bn2(x)
        x=self.lrelu_2(x)
        
        return x

class UNet_SAB_STUDENT(nn.Module):

    def __init__(self, in_channels=3, out_channels=1, init_features=32):
        super(UNet_SAB_STUDENT, self).__init__()

        features = init_features
        self.encoder1 = DoubleConv_for_EPAB(in_channels, features)

        self.pool1 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder2 = UNet_SAB_STUDENT._block(features, features * 2, name="enc2")
        self.pool2 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder3 = UNet_SAB_STUDENT._block(features * 2, features * 4, name="enc3")
        self.pool3 = nn.MaxPool2d(kernel_size=2, stride=2)
        self.encoder4 = UNet_SAB_STUDENT._block(features * 4, features * 8, name="enc4")
        self.pool4 = nn.MaxPool2d(kernel_size=2, stride=2)

        self.bottleneck = UNet_SAB_STUDENT._block(features * 8, features * 16, name="bottleneck")

        self.upconv4 = nn.ConvTranspose2d(
            features * 16, features * 8, kernel_size=2, stride=2
        )
        self.decoder4 = UNet_SAB_STUDENT._block((features * 8) * 2, features * 8, name="dec4")
        self.upconv3 = nn.ConvTranspose2d(
            features * 8, features * 4, kernel_size=2, stride=2
        )
        self.decoder3 = UNet_SAB_STUDENT._block((features * 4) * 2, features * 4, name="dec3")
        self.upconv2 = nn.ConvTranspose2d(
            features * 4, features * 2, kernel_size=2, stride=2
        )
        self.decoder2 = UNet_SAB_STUDENT._block((features * 2) * 2, features * 2, name="dec2")
        self.upconv1 = nn.ConvTranspose2d(
            features * 2, features, kernel_size=2, stride=2
        )
        self.decoder1 = UNet_SAB_STUDENT._block(features * 2, features, name="dec1")

        self.conv = nn.Conv2d(
            in_channels=features, out_channels=out_channels, kernel_size=1
        )

    def forward(self, x):
        enc1 = self.encoder1(x)
        
        enc2 = self.encoder2(self.pool1(enc1))
      
        enc3 = self.encoder3(self.pool2(enc2))
       
        enc4 = self.encoder4(self.pool3(enc3))
        

        bottleneck = self.bottleneck(self.pool4(enc4))
        

        dec4 = self.upconv4(bottleneck)
        dec4 = torch.cat((dec4, enc4), dim=1)
        dec4 = self.decoder4(dec4)
       
        dec3 = self.upconv3(dec4)
        
        dec3 = torch.cat((dec3, enc3), dim=1)
        dec3 = self.decoder3(dec3)
        dec2 = self.upconv2(dec3)
        dec2 = torch.cat((dec2, enc2), dim=1)
        dec2 = self.decoder2(dec2)
        dec1 = self.upconv1(dec2)
        dec1 = torch.cat((dec1, enc1), dim=1)
        dec1 = self.decoder1(dec1)
        return torch.sigmoid(self.conv(dec1)),enc1,enc3,dec3,dec1

    @staticmethod
    def _block(in_channels, features, name):
        
        layer1a=nn.Conv2d(in_channels,features,(1,5),padding=(0,2),groups=16,bias=False)
        nn.init.kaiming_uniform_(layer1a.weight,mode='fan_in')

        layer2a=nn.Conv2d(features,features,1,bias=False)
        nn.init.kaiming_uniform_(layer2a.weight,mode='fan_in')



        
        
        layer1b=nn.Conv2d(features,features,(5,1),padding=(2,0),groups=16,bias=False)
        nn.init.kaiming_uniform_(layer1b.weight,mode='fan_in')

        layer2b=nn.Conv2d(features,features,1,bias=False)
        nn.init.kaiming_uniform_(layer2b.weight,mode='fan_in')

    
        return nn.Sequential(
            OrderedDict(
                [
                    
                    (name + "P_conv1",layer1a),
                    (name + "D_conv1",layer2a),

                    (name + "norm1", nn.BatchNorm2d(num_features=features)),
                    (name + "relu1", nn.ReLU(inplace=True)),
                    
                    (name + "Pconv2",layer1b),
                    (name + "Dconv2",layer2b),
                    
                    
                    (name + "norm2", nn.BatchNorm2d(num_features=features)),
                    (name + "relu2", nn.ReLU(inplace=True)),
                ]
            )
        )

