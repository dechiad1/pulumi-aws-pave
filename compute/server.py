from pulumi.resource import ComponentResource, ResourceOptions
import pulumi_aws as aws


class Server(ComponentResource):
    """
    Create a single ec2 in the public security group to be used as a bastion

    :param name The name of the servef
    :param size The size of the ec2 instance
    :param security_groups A list of security group ids to attach to the ec2
    :param tags A dictionary of tags to attach to the instance
    """
    def __init__(self, name, size="t2.micro", security_groups=None, tags=None, subnet_id=None, key=None):
        ComponentResource.__init__(self, "aws:compute:dtd", name, None, None)

        type = tags['type']

        self.user_data = _get_user_data(type)
        self.ami_id = _get_ami()
        self.size = size
        self.name = name
        self.security_groups = security_groups
        self.subnet_id = subnet_id

        server = aws.ec2.Instance(self.name, instance_type=self.size, security_groups=self.security_groups,
                                  tags=tags, ami=self.ami_id, user_data=self.user_data, key_name=key,
                                  associate_public_ip_address=_get_public_ip(type), subnet_id=self.subnet_id,
                                  __opts__= ResourceOptions(parent=self))

        self.public_dns = server.public_dns


def _get_ami():
    ami = aws.get_ami(most_recent=True, owners=["amazon"], filters=[{"name": "name", "values" :["amzn-ami-hvm-*"]}])
    return ami.id


def _get_user_data(type):
    if type == "bastion" or type == "Bastion":
        return None
    else:
        return None


def _get_public_ip(type):
    if type == "bastion" or type == "Bastion":
        return True
    else:
        return False

# TODO: method to create keypair for private ec2s. The private should be injected to this via userdata.
# public should be returned for injecting into the others.
