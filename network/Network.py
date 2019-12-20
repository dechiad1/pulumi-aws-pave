from pulumi.resource import ComponentResource, ResourceOptions
from pulumi.errors import RunError
from pulumi_aws import ec2
import pulumi_aws

import util.Util as Util

class Network(ComponentResource):
    """
    Create a vpc with x subnets. At a maximum, one will be public and the rest will be private. The public subnet will have a NAT gateway.
    Security groups will be created for the current IP address managing the stack.

    :param name The name of the vpc
    :param port_list The ports to whitelist
    :param subnet_count The amount of subnets to create
    :param vpc_tags Dictionary of tags to attach to the VPC
    :param sg_tags Dictionary of tags to attach to the security groups created
    """
    def __init__(self, name, port_list=None, subnet_count=0, vpc_tags=None, sg_tags=None, private_subnets=None, security_group_ids=None, public_subnets=None):
        ComponentResource.__init__(self, "aws:network:dtd", name, {
            "number_of_availability_zones": subnet_count,
            "use_private_subnets": True,
            "subnet_ids": private_subnets,
            "security_group_ids": security_group_ids,
            "public_subnet_ids": public_subnets
        }, None)

        self.name = name
        self.port_list = port_list
        self.subnet_count = subnet_count
        self.vpc_tags = vpc_tags
        self.sg_tags = sg_tags
        self.public_subnets = []
        self.private_subnets = []
        self.security_group_ids = []
        self.vpcid = None

        PUBLIC_SUBNET_COUNT = 0

        if subnet_count < 2 or subnet_count > 3:
            raise RunError("Unsupported amount of subnets! 2 or 3 supported. %d entered" % subnet_count)

        # create the VPC
        vpc = ec2.Vpc(
            name,
            cidr_block="10.0.0.0/16",
            enable_dns_hostnames=True,
            enable_dns_support=True,
            tags=vpc_tags,
            __opts__= ResourceOptions(parent=self)
        )

        self.vpcid = vpc.id

        public_route_table_id = self._create_public_subnet_route_table(vpc.id)
        private_route_table_id = None

        # create the subnets
        for i in range(subnet_count):
            # create public subnet(s) first
            if i <= PUBLIC_SUBNET_COUNT:
                self.public_subnets.append(self._create_public_subnet(vpc.id, public_route_table_id, i))
            # create private subnet(s) next
            else:
                # do create the private route table, eip & NAT just once
                if i == 1:
                    public_subnet_id = self.public_subnets[0]
                    private_route_table_id = self._create_private_subnet_route_table(public_subnet_id, vpc.id)
                self.private_subnets.append(self._create_private_subnet(vpc.id, private_route_table_id, i))


        self.security_group_ids = self._create_security_groups(vpc.id)
        self.public_sg = self.security_group_ids['public']
        self.private_sg = self.security_group_ids['private']

        # This does not work because the items in the dictionary are of type Output
        # for k in all_security_group_ids:
        #     print(k)
        #     if "public" in k:
        #         self.public_security_groups.append(all_security_group_ids[k])
        #     elif "private" in k:
        #         self.private_security_groups.append(all_security_group_ids[k])
        # self.security_group_ids = list(all_security_group_ids)

        # this may be unnecessary - it is a nice to have for the UI for now
        self.register_outputs({
            "vpc_id": vpc.id,
            "private_subnet_ids": self.private_subnets,
            "public_subnet_ids": self.public_subnet_ids,
            "security_group_ids": self.security_group_ids
        })

    def _get_az(self, index):
        zones = pulumi_aws.get_availability_zones()
        return zones.zone_ids[index]

    def _create_public_subnet_route_table(self, vpcid):
        # create the public subnet for the NAT
        ig_name = "%s-ig" % self.name
        internet_gateway = ec2.InternetGateway(ig_name, vpc_id=vpcid, tags=self.vpc_tags, __opts__= ResourceOptions(parent=self))
        rt_name = "%s-public-rt" % self.name
        public_route_table = ec2.RouteTable(rt_name, vpc_id=vpcid, routes=[{
            "cidrBlock": "0.0.0.0/0",
            "gatewayId": internet_gateway.id
        }], __opts__= ResourceOptions(parent=self))
        return public_route_table.id

    def _create_public_subnet(self, vpcid, public_route_table_id, azid):
        subnet_name = "%s-%d-public-subnet" % (self.name, azid)
        az_id = self._get_az(azid)
        subnet = ec2.Subnet(subnet_name, availability_zone_id=az_id, cidr_block=("10.0.%d.0/24" % azid), vpc_id=vpcid, tags=self.vpc_tags,
                            map_public_ip_on_launch=True, __opts__= ResourceOptions(parent=self))

        prta_name = "%s-rt-assoc" % subnet_name
        public_route_table_association = ec2.RouteTableAssociation(prta_name, route_table_id=public_route_table_id, subnet_id=subnet.id, __opts__= ResourceOptions(parent=self))
        return subnet.id

    # needs the public subnet id to pass into the NAT gateway
    def _create_private_subnet_route_table(self, public_subnet_id, vpcid):
        eip_name = "%s-nat-eip" % self.name
        nat_name = "%s-nat" % self.name
        eip = ec2.Eip(eip_name, __opts__= ResourceOptions(parent=self))
        nat_gateway = ec2.NatGateway(nat_name, subnet_id=public_subnet_id, allocation_id=eip.id, tags=self.vpc_tags, __opts__=ResourceOptions(parent=self))
        rt_name = "%s-private-rt" % self.name
        private_route_table = ec2.RouteTable(rt_name, vpc_id=vpcid, routes=[{
            "cidrBlock": "0.0.0.0/0",
            "gatewayId": nat_gateway.id
        }], __opts__= ResourceOptions(parent=self))
        return private_route_table.id

    def _create_private_subnet(self, vpcid, private_route_table_id, azid):
        if private_route_table_id is None:
            raise RunError("attempting to create a private subnet without a private subnet route table")

        subnet_name = "%s-%d-private-subnet" % (self.name, azid)
        az_id = self._get_az(azid)
        subnet = ec2.Subnet(subnet_name, availability_zone_id=az_id, cidr_block=("10.0.%d.0/24" % azid), vpc_id=vpcid, tags=self.vpc_tags,
                            map_public_ip_on_launch=False, __opts__= ResourceOptions(parent=self))

        prta_name = "%s-rt-assoc" % subnet_name
        private_route_table_assocation = ec2.RouteTableAssociation(prta_name, route_table_id=private_route_table_id, subnet_id=subnet.id, __opts__=ResourceOptions(parent=self))
        return subnet.id

    def _create_security_groups(self, vpcid):
        pub_name = "%s-public-sg" % self.name
        public_sg = ec2.SecurityGroup(pub_name, description=pub_name, vpc_id=vpcid, tags=self.sg_tags, __opts__= ResourceOptions(parent=self))

        priv_name = "%s-private-sg" % self.name
        private_sg = ec2.SecurityGroup(priv_name, description=priv_name, vpc_id=vpcid, tags=self.sg_tags, __opts__= ResourceOptions(parent=self))

        """
        Set up public rules:
            1. ingress from itself to itself
            2. ingress from private to public
            3. egress rule for all
            4. ingress rule for current IP address on 22
        """
        pub_ingress_itself = ec2.SecurityGroupRule("public-ingress-from-itself", type="ingress", from_port=0, to_port=0,
                                                   protocol=-1, security_group_id=public_sg.id, self=True, __opts__= ResourceOptions(parent=self))

        pub_ingress_private = ec2.SecurityGroupRule("public-ingress-from-private", type="ingress", from_port=0, to_port=0,
                                                    protocol=-1, security_group_id=public_sg.id, source_security_group_id=private_sg.id, __opts__= ResourceOptions(parent=self))

        pub_egress = ec2.SecurityGroupRule("public-egress", type="egress", cidr_blocks=["0.0.0.0/0"], from_port=0,
                                           to_port=0, protocol=-1, security_group_id=public_sg.id, description="egress traffic from public sg", __opts__= ResourceOptions(parent=self))

        current_ip = Util.get_workstation_ip()
        pub_ingress_current_ip = ec2.SecurityGroupRule("public-ingress-from-current-ip", type="ingress", from_port=22, to_port=22,
                                                       protocol="TCP", security_group_id=public_sg.id, cidr_blocks=[("%s/32" % current_ip)], __opts__= ResourceOptions(parent=self))
        """
        Set up private rules:
            1. ingress from public to it
            2. ingress from itself to itself
            3. egress rule for all
        """
        priv_ingress_itself = ec2.SecurityGroupRule("private-ingress-from-itself", type="ingress", from_port=0, to_port=0,
                                                   protocol=-1, security_group_id=private_sg.id, self=True, __opts__= ResourceOptions(parent=self))

        priv_ingress_public = ec2.SecurityGroupRule("private-ingress-from-private", type="ingress", from_port=0, to_port=0,
                                                protocol=-1, security_group_id=private_sg.id, source_security_group_id=public_sg.id, __opts__= ResourceOptions(parent=self))

        priv_egress = ec2.SecurityGroupRule("private-egress", type="egress", cidr_blocks=["0.0.0.0/0"], from_port=0,
                                       to_port=0, protocol=-1, security_group_id=private_sg.id, description="egress traffic from private sg", __opts__= ResourceOptions(parent=self))

        return {"public": public_sg.id, "private": private_sg.id}
