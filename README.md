## AWS env managed by pulumi
<br>

Create a __main__.py file and use the classes provided

<br>

Create a VPC with 2 private subnets, 1 public subnet & SGs for each. The public subnet includes ingress to 22 from the current IP
```
name = "network"
 subnet_count = 3
 vpc_tags = {
     "Name": "network"
 }
 sg_tags = {
     "Name": "network"
 }
 
 network = Network(name, subnet_count=subnet_count, vpc_tags=vpc_tags, sg_tags=sg_tags)
```

Create a bastion. This example places it in the public subnet of the aforementioned network.
```
server_name = "bastion"
server_tags = {
    "Name": "bastion",
    "type": "bastion"
}

subnet_id = network.public_subnets[0]

server = Server(server_name, security_groups=[network.public_sg], tags=server_tags, subnet_id=subnet_id, key_name = None)
```
pulumi up

