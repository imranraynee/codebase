# codebase

wget https://www.python.org/ftp/python/3.11.8/Python-3.11.8.tgz

mkdir -p python-deps
dnf download --destdir=./python-deps \
    zlib-devel bzip2-devel openssl-devel ncurses-devel \
    sqlite-devel readline-devel tk-devel gdbm-devel \
    libffi-devel xz-devel libuuid-devel gcc make \
    gcc-c++ glibc-devel libnsl2-devel

    wget https://bootstrap.pypa.io/get-pip.py -O get-pip.py

    sudo dnf install ./python-deps/*.rpm

    tar xzf Python-3.11.8.tgz
cd Python-3.11.8

# Configure with optimizations
./configure --enable-optimizations --with-ensurepip=install

# Build and install (using altinstall to avoid replacing system Python)
make -j$(nproc)
sudo make altinstall
