## Server in private subnet

Use the below template to create a vpc with public & private subnets, 
a bastion in the public subnet & a server in the private subnet. The 
code will generate a keypair, set the public key as an authorized key 
on the server in the private subnet & will inject the private key into
bastion server on startup. 

The example also bootstraps security groups for each server to allow 
traffic from the executing machine's IP on 22 only into the bastion &
traffic between security groups. 

```
from network.Network import Network
from compute.Server import Server
import util.Util as util
from pulumi_aws import ec2
import pulumi

name = "network"
subnet_count = 3
vpc_tags = {
    "Name": "network"
}
sg_tags = {
    "Name": "network"
}

network = Network(name, subnet_count=subnet_count, vpc_tags=vpc_tags, sg_tags=sg_tags)

server_name = "bastion"
server_tags = {
    "Name": "bastion",
    "type": "bastion"
}

subnet_id = network.public_subnets[0]

bastion_keycontents = open('pulumi_rsa.pub').read()
bastion_keypair = ec2.KeyPair("keypair", key_name="keypair", public_key=bastion_keycontents)

bastion_to_private_keys = util.create_bastion_to_private_keypair()
user_data_dict = {
    'type': 'bastion',
    'private': bastion_to_private_keys['private']
}

server = Server(server_name, security_groups=[network.public_sg], tags=server_tags, subnet_id=subnet_id,
                key="keypair", user_data_dict=user_data_dict)


bastion_to_server_keypair = ec2.KeyPair("bastion-to-server", key_name="bastion-to-server",
                                        public_key=str(bastion_to_private_keys['public']))

private_server_tags = {
    "Name": "private",
    "type": "server"
}

private_server = Server("private", security_groups=[network.private_sg], tags=private_server_tags,
                        subnet_id=network.private_subnets[0], key="bastion-to-server")

pulumi.export("public dns of bastion", server.public_dns)
pulumi.export("private ip of server", private_server.private_ip)

```